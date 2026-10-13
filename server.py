import hmac
import ipaddress
import base64
import binascii
import json
import os
import secrets
import threading
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from runner import run_code
from storage import class_code_status, create_student_session, delete_student_session, get_submission, import_students, init_db, list_students, list_submissions, progress_page, save_submission, session_student, set_class_code, student_exists, student_progress, verify_class_code

ROOT = Path(__file__).parent
PROBLEMS_FILE = ROOT / "problems.json"
WEEKS_FILE = ROOT / "weeks.json"
ADMIN_TOKEN = "AS006"
DATA_LOCK = threading.RLock()
SLOTS = threading.BoundedSemaphore(2)
ALLOWED_SUBNETS = [ipaddress.ip_network(item.strip(), strict=False) for item in os.environ.get("JUDGE_ALLOWED_SUBNETS", "").split(",") if item.strip()]
HOST = os.environ.get("JUDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("JUDGE_PORT", "8000"))


init_db()


def read_data():
    with DATA_LOCK:
        problems = json.loads(PROBLEMS_FILE.read_text(encoding="utf-8"))
        weeks = json.loads(WEEKS_FILE.read_text(encoding="utf-8"))
        return weeks, problems


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def short_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label}: 1~{limit}자 문자열을 입력하세요.")
    return value.strip()


def test_case(value):
    if not isinstance(value, dict):
        raise ValueError("테스트 케이스 형식이 올바르지 않습니다.")
    stdin, stdout = value.get("input"), value.get("output")
    if not isinstance(stdin, str) or not isinstance(stdout, str) or len(stdin.encode("utf-8")) > 8000 or len(stdout.encode("utf-8")) > 8000:
        raise ValueError("테스트 입력과 출력은 각각 8KB 이하여야 합니다.")
    return {"input": stdin, "output": stdout}


class Handler(BaseHTTPRequestHandler):
    def allowed_client(self):
        if not ALLOWED_SUBNETS:
            return True
        address = ipaddress.ip_address(self.client_address[0])
        return address.is_loopback or any(address in subnet for subnet in ALLOWED_SUBNETS)

    def reply(self, status, payload, headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def html(self, name):
        data = (ROOT / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, token):
        return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

    def session_token(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["judge_session"].value if "judge_session" in cookie else ""
        except CookieError:
            return ""

    def current_student(self):
        return session_student(self.session_token())

    def do_GET(self):
        if not self.allowed_client():
            return self.reply(403, {"error": "허용된 내부망에서만 접속할 수 있습니다."})
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/":
            return self.html("index.html")
        if path == "/admin":
            return self.html("admin.html")
        if path == "/styles.css":
            data = (ROOT / "styles.css").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/fonts/PretendardVariable.woff2":
            data = (ROOT / "fonts" / "PretendardVariable.woff2").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "font/woff2")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/weeks":
            if not self.current_student() and not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "학생 로그인이 필요합니다."})
            return self.reply(200, read_data()[0])
        if path == "/api/problems":
            if not self.current_student() and not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "학생 로그인이 필요합니다."})
            return self.reply(200, [{key: value for key, value in problem.items() if key != "tests"} for problem in read_data()[1]])
        if path in ("/api/student/me", "/api/student/progress"):
            student = self.current_student()
            if not student:
                return self.reply(401, {"error": "학생 로그인이 필요합니다."})
            if path.endswith("/me"):
                return self.reply(200, student)
            weeks, problems = read_data()
            return self.reply(200, student_progress(student["student_id"], weeks, problems))
        if path == "/api/admin/problems":
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
            return self.reply(200, read_data()[1])
        if path == "/api/admin/class-code":
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
            return self.reply(200, class_code_status())
        if path in ("/api/admin/students", "/api/admin/submissions"):
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
            return self.reply(200, list_students() if path.endswith("/students") else list_submissions())
        if path == "/api/admin/progress":
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
            parameters = parse_qs(parsed_url.query)
            query = parameters.get("query", [""])[0].strip()[:100]
            try:
                offset = max(0, int(parameters.get("offset", ["0"])[0]))
            except ValueError:
                return self.reply(400, {"error": "offset은 숫자여야 합니다."})
            weeks, problems = read_data()
            return self.reply(200, progress_page(weeks, problems, query, offset))
        if path.startswith("/api/admin/submissions/"):
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
            try:
                submission_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self.reply(400, {"error": "제출 번호가 올바르지 않습니다."})
            submission = get_submission(submission_id)
            return self.reply(200, submission) if submission else self.reply(404, {"error": "제출을 찾을 수 없습니다."})
        return self.reply(404, {"error": "찾을 수 없습니다."})

    def do_POST(self):
        if not self.allowed_client():
            return self.reply(403, {"error": "허용된 내부망에서만 접속할 수 있습니다."})
        path = urlparse(self.path).path
        if path not in ("/api/run", "/api/submit", "/api/student/login", "/api/student/logout", "/api/admin/weeks", "/api/admin/problems", "/api/admin/class-code", "/api/admin/students/import"):
            return self.reply(404, {"error": "찾을 수 없습니다."})
        student = None
        if path.startswith("/api/admin/"):
            if not self.authorized(ADMIN_TOKEN):
                return self.reply(401, {"error": "관리자 토큰이 올바르지 않습니다."})
        elif path in ("/api/run", "/api/submit"):
            student = self.current_student()
            if not student:
                return self.reply(401, {"error": "학생 로그인이 필요합니다."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 3_000_000 if path == "/api/admin/students/import" else 40_000
            if length < 1 or length > limit:
                return self.reply(413, {"error": f"요청은 {limit}바이트 이하여야 합니다."})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON 객체를 보내세요.")
            if path == "/api/student/logout":
                delete_student_session(self.session_token())
                return self.reply(200, {"ok": True}, {"Set-Cookie": "judge_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
            if path == "/api/student/login":
                student_id = short_text(body.get("student_id"), "학번", 40)
                student_name = short_text(body.get("student_name"), "이름", 100)
                if not student_exists(student_id, student_name) or not verify_class_code(body.get("class_code")):
                    return self.reply(401, {"error": "학번, 이름 또는 수업 코드가 올바르지 않습니다."})
                delete_student_session(self.session_token())
                session = create_student_session(student_id)
                return self.reply(200, {"student_id": student_id, "name": student_name},
                                  {"Set-Cookie": f"judge_session={session}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"})
            if path == "/api/admin/class-code":
                return self.reply(200, set_class_code(body.get("code")))
            if path == "/api/admin/students/import":
                filename = body.get("filename", "")
                encoded = body.get("data", "")
                if not isinstance(filename, str) or not filename.lower().endswith(".xlsx") or not isinstance(encoded, str):
                    raise ValueError(".xlsx 파일을 선택하세요.")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except binascii.Error as exc:
                    raise ValueError("엑셀 파일을 읽을 수 없습니다.") from exc
                return self.reply(200, import_students(content))
            if path == "/api/admin/weeks":
                title = short_text(body.get("title"), "주차 이름", 80)
                with DATA_LOCK:
                    weeks, _ = read_data()
                    if any(w["title"] == title for w in weeks):
                        raise ValueError("같은 이름의 주차가 이미 있습니다.")
                    week = {"id": "week-" + secrets.token_hex(6), "title": title}
                    weeks.append(week)
                    save_json(WEEKS_FILE, weeks)
                return self.reply(201, week)
            if path == "/api/admin/problems":
                title = short_text(body.get("title"), "문제 제목", 120)
                description = short_text(body.get("description"), "문제 설명", 5000)
                input_desc = short_text(body.get("input"), "입력 설명", 2000)
                output_desc = short_text(body.get("output"), "출력 설명", 2000)
                samples, tests = body.get("samples"), body.get("tests")
                if not isinstance(samples, list) or not 1 <= len(samples) <= 10:
                    raise ValueError("예제를 1~10개 입력하세요.")
                if not isinstance(tests, list) or not 1 <= len(tests) <= 30:
                    raise ValueError("채점 테스트를 1~30개 입력하세요.")
                problem = {"id": "problem-" + secrets.token_hex(6), "week_id": body.get("week_id"),
                           "title": title, "description": description, "input": input_desc,
                           "output": output_desc, "samples": [test_case(x) for x in samples],
                           "tests": [test_case(x) for x in tests]}
                with DATA_LOCK:
                    weeks, problems = read_data()
                    if problem["week_id"] not in [w["id"] for w in weeks]:
                        raise ValueError("주차를 선택하세요.")
                    problems.append(problem)
                    save_json(PROBLEMS_FILE, problems)
                return self.reply(201, {key: value for key, value in problem.items() if key != "tests"})
            code = body["code"]
            if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > 32000:
                raise ValueError("Python 코드는 1~32KB여야 합니다.")
            if path == "/api/run":
                stdin = body.get("stdin", "")
                if not isinstance(stdin, str) or len(stdin.encode("utf-8")) > 8000:
                    raise ValueError("입력은 8KB 이하여야 합니다.")
            else:
                problem = next((p for p in read_data()[1] if p["id"] == body.get("problem_id")), None)
                if problem is None:
                    raise ValueError("문제를 선택하세요.")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            return self.reply(400, {"error": str(exc)})
        if not SLOTS.acquire(blocking=False):
            return self.reply(429, {"error": "실행 중인 제출이 많습니다. 잠시 후 다시 시도하세요."})
        try:
            if path == "/api/run":
                return self.reply(200, run_code(code, stdin))
            cases = []
            verdict = "ACCEPTED"
            for test in problem["tests"]:
                result = run_code(code, test["input"])
                passed = result["status"] == "OK" and result["stdout"].rstrip() == test["output"].rstrip()
                cases.append({"passed": passed, "status": result["status"]})
                if not passed:
                    verdict = "WRONG_ANSWER" if result["status"] == "OK" else result["status"]
                    break
            passed_count = sum(c["passed"] for c in cases)
            entry = body.get("entry")
            submission_id = save_submission(student["student_id"], problem["id"], code, verdict, passed_count, len(problem["tests"]), entry)
            return self.reply(200, {"submission_id": submission_id, "entry_method": get_submission(submission_id)["entry_method"],
                                    "verdict": verdict, "passed": passed_count,
                                    "total": len(problem["tests"]), "cases": cases})
        finally:
            SLOTS.release()


if __name__ == "__main__":
    if HOST not in ("127.0.0.1", "localhost", "::1") and not ALLOWED_SUBNETS:
        raise SystemExit("외부 주소에 바인딩하려면 JUDGE_ALLOWED_SUBNETS를 설정하세요.")
    print(f"Python Judge: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
