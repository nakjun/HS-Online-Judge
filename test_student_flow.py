import base64
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from openpyxl import Workbook

import server
import storage


class StudentFlowTest(unittest.TestCase):
    def test_excel_import_identity_and_saved_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db, old_runner = storage.DB_PATH, server.run_code
            httpd = None
            try:
                storage.DB_PATH = Path(directory) / "judge.db"
                storage.init_db()
                server.run_code = lambda code, stdin: {"status": "OK", "stdout": str(sum(map(int, stdin.split()))) + "\n", "stderr": ""}
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(["학번", "이름"])
                sheet.append(["00123", "김학생"])
                output = io.BytesIO()
                workbook.save(output)
                workbook.close()
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                session_cookie = ""

                def request(path, body, admin=False):
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                    headers = {"Content-Type": "application/json"}
                    if admin:
                        headers["Authorization"] = "Bearer " + server.ADMIN_TOKEN
                    elif session_cookie:
                        headers["Cookie"] = session_cookie
                    connection.request("POST", path, json.dumps(body, ensure_ascii=False).encode("utf-8"), headers)
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    connection.close()
                    return result

                roster = {"filename": "students.xlsx", "data": base64.b64encode(output.getvalue()).decode("ascii")}
                self.assertEqual(request("/api/admin/students/import", roster)[0], 401)
                status, imported = request("/api/admin/students/import", roster, True)
                self.assertEqual((status, imported["created"]), (200, 1))
                body = {"problem_id": "sum-two", "student_id": "00123", "student_name": "김학생",
                        "code": "a,b=map(int,input().split());print(a+b)",
                        "entry": {"largest_paste_chars": 42, "pasted_chars": 42, "typed_chars": 0, "file_upload": False}}
                self.assertEqual(request("/api/submit", body)[0], 401)
                self.assertEqual(request("/api/student/login", {"student_id": "00123", "student_name": "다른이름", "class_code": "AS006"})[0], 401)
                self.assertEqual(request("/api/student/login", {"student_id": "00123", "student_name": "김학생", "class_code": "wrong"})[0], 401)
                connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                connection.request("POST", "/api/student/login",
                                   json.dumps({"student_id": "00123", "student_name": "김학생", "class_code": "AS006"}, ensure_ascii=False).encode("utf-8"),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                session_cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                self.assertEqual(response.status, 200)
                response.read()
                connection.close()
                status, result = request("/api/submit", body)
                self.assertEqual((status, result["verdict"], result["passed"]), (200, "ACCEPTED", 3))
                self.assertEqual(storage.list_submissions()[0]["student_id"], "00123")
                self.assertEqual(storage.list_submissions()[0]["entry_method"], "FULL_PASTE")
                self.assertEqual(storage.get_submission(result["submission_id"])["code"], body["code"])
                connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                connection.request("GET", "/api/student/progress", headers={"Cookie": session_cookie})
                response = connection.getresponse()
                student_progress = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertTrue(student_progress[0]["problems"][0]["solved"])
                weeks = [{"id": "week-1", "title": "1주차"}, {"id": "week-2", "title": "2주차"}]
                problems = [{"id": "sum-two", "week_id": "week-1", "title": "두 수의 합"},
                            {"id": "later", "week_id": "week-2", "title": "다음 문제"}]
                progress = storage.progress_page(weeks, problems, "00123")
                self.assertEqual(progress["total_students"], 1)
                self.assertEqual(progress["rows"][0]["weeks"][0]["submitted"], 1)
                self.assertEqual(progress["rows"][0]["weeks"][0]["accepted"], 1)
                self.assertEqual(progress["rows"][0]["weeks"][1]["submitted"], 0)
                connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                connection.request("GET", "/api/admin/progress?query=00123",
                                   headers={"Authorization": "Bearer " + server.ADMIN_TOKEN})
                response = connection.getresponse()
                api_progress = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertEqual(api_progress["rows"][0]["student_id"], "00123")
                self.assertEqual(request("/api/admin/class-code", {"code": "NEW789"})[0], 401)
                self.assertEqual(request("/api/admin/class-code", {"code": "NEW789"}, True)[0], 200)
                self.assertFalse(storage.verify_class_code("AS006"))
                self.assertTrue(storage.verify_class_code("NEW789"))
                self.assertEqual(request("/api/student/login", {"student_id": "00123", "student_name": "김학생", "class_code": "AS006"})[0], 401)
                connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                connection.request("GET", "/api/student/progress", headers={"Cookie": session_cookie})
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                connection.close()
                self.assertEqual(request("/api/student/login", {"student_id": "00123", "student_name": "김학생", "class_code": "NEW789"})[0], 200)
            finally:
                if httpd:
                    httpd.shutdown()
                    httpd.server_close()
                storage.DB_PATH, server.run_code = old_db, old_runner


if __name__ == "__main__":
    unittest.main()
