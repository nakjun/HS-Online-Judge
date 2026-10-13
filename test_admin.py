import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import server


class AdminApiTest(unittest.TestCase):
    def test_create_week_and_problem_with_private_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            old_weeks, old_problems = server.WEEKS_FILE, server.PROBLEMS_FILE
            try:
                server.WEEKS_FILE = Path(directory) / "weeks.json"
                server.PROBLEMS_FILE = Path(directory) / "problems.json"
                server.WEEKS_FILE.write_text("[]", encoding="utf-8")
                server.PROBLEMS_FILE.write_text("[]", encoding="utf-8")
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()

                def request(method, path, body=None, authorized=False):
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
                    headers = {"Content-Type": "application/json"}
                    if authorized:
                        headers["Authorization"] = "Bearer " + server.ADMIN_TOKEN
                    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    connection.close()
                    return result

                self.assertEqual(request("POST", "/api/admin/weeks", {"title": "2주차"})[0], 401)
                status, week = request("POST", "/api/admin/weeks", {"title": "2주차"}, True)
                self.assertEqual(status, 201)
                problem = {"week_id": week["id"], "title": "제곱", "description": "수를 제곱하세요.",
                           "input": "정수 하나", "output": "제곱한 값",
                           "samples": [{"input": "2\n", "output": "4\n"}],
                           "tests": [{"input": "3\n", "output": "9\n"}]}
                self.assertEqual(request("POST", "/api/admin/problems", problem, True)[0], 201)
                self.assertEqual(request("GET", "/api/problems")[0], 401)
                public = request("GET", "/api/problems", authorized=True)[1]
                self.assertNotIn("tests", public[0])
                self.assertEqual(public[0]["week_id"], week["id"])
                self.assertEqual(request("GET", "/api/admin/problems", authorized=True)[1][0]["tests"], problem["tests"])
                self.assertEqual(json.loads(server.PROBLEMS_FILE.read_text(encoding="utf-8"))[0]["tests"], problem["tests"])
            finally:
                if "httpd" in locals():
                    httpd.shutdown()
                    httpd.server_close()
                server.WEEKS_FILE, server.PROBLEMS_FILE = old_weeks, old_problems


if __name__ == "__main__":
    unittest.main()
