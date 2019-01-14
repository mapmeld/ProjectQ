#   Copyright 2017 ProjectQ-Framework (www.projectq.ch)
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""Tests for projectq.backends._rigetti_http_client._rigetti.py."""

import json
import pytest
import requests
from requests.compat import urljoin

from projectq.backends._rigetti import _rigetti_http_client


# Insure that no HTTP request can be made in all tests in this module
@pytest.fixture(autouse=True)
def no_requests(monkeypatch):
    monkeypatch.delattr("requests.sessions.Session.request")


_api_url = "https://job.rigetti.com/beta/"
_api_url_status = "https://job.rigetti.com/beta/devices"


def test_send_real_device_online_verbose(monkeypatch):
    quils = {'quils': [{'quil': 'my quil'}]}
    json_quil = json.dumps(quils)
    name = 'projectq_test'
    access_token = "access"
    user_id = 2016
    code_id = 11
    name_item = '"name":"{name}", "jsonquil":'.format(name=name)
    json_body = ''.join([name_item, json_quil])
    json_data = ''.join(['{', json_body, '}'])
    shots = 1
    device = "8Q-Agave"
    json_data_run = ''.join(['{"quil":', json_quil, '}'])
    execution_id = 3
    result_ready = [False]
    result = "my_result"
    request_num = [0]  # To assert correct order of calls

    # Mock of Rigetti server:
    def mocked_requests_get(*args, **kwargs):
        class MockRequest:
            def __init__(self, url=""):
                self.url = url

        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code
                self.request = MockRequest()
                self.text = ""

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        # Accessing status of device. Return online.
        status_url = '/devices'
        if (args[0] == urljoin(_api_url_status, status_url) and
                (request_num[0] == 0 or request_num[0] == 3)):
            request_num[0] += 1
            return MockResponse({"state": True}, 200)
        # Getting result
        elif (args[0] == urljoin(_api_url,
              "Jobs/{execution_id}".format(execution_id=execution_id)) and
              kwargs["params"]["access_token"] == access_token and not
              result_ready[0] and request_num[0] == 3):
            result_ready[0] = True
            return MockResponse({"status": {"id": "NotDone"}}, 200)
        elif (args[0] == urljoin(_api_url,
              "Jobs/{execution_id}".format(execution_id=execution_id)) and
              kwargs["params"]["access_token"] == access_token and
              result_ready[0] and request_num[0] == 4):
            print("state ok")
            return MockResponse({"quils": [{"result": result}]}, 200)

    def mocked_requests_post(*args, **kwargs):
        class MockRequest:
            def __init__(self, body="", url=""):
                self.body = body
                self.url = url

        class MockPostResponse:
            def __init__(self, json_data, text=" "):
                self.json_data = json_data
                self.text = text
                self.request = MockRequest()

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        # Run code
        if (args[0] == urljoin(_api_url, "Jobs") and
                kwargs["data"] == json_quil and
                kwargs["params"]["access_token"] == access_token and
                kwargs["params"]["deviceRunType"] == device and
                kwargs["params"]["fromCache"] == "false" and
                kwargs["params"]["shots"] == shots and
                kwargs["headers"]["Content-Type"] == "application/json" and
                request_num[0] == 2):
            request_num[0] += 1
            return MockPostResponse({"id": execution_id})

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    # Patch login data
    api_key = "test"
    user_id = "test@projectq.ch"
    monkeypatch.setitem(__builtins__, "input", lambda x: user_id)
    monkeypatch.setitem(__builtins__, "raw_input", lambda x: user_id)

    def user_api_key_input(prompt):
        if prompt == "Rigetti Forest API Key > ":
            return api_key

    monkeypatch.setattr("getpass.getpass", user_api_key_input)

    # Code to test:
    res = _rigetti_http_client.send(json_quil,
                                device="8Q-Agave",
                                user=None, password=None,
                                shots=shots, verbose=True)
    print(res)
    assert res == result


def test_send_real_device_offline(monkeypatch):
    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url_status, status_url):
            return MockResponse({"state": False}, 200)
    monkeypatch.setattr("requests.get", mocked_requests_get)
    shots = 1
    json_quil = "my_json_quil"
    name = 'projectq_test'
    with pytest.raises(_rigetti_http_client.DeviceOfflineError):
        _rigetti_http_client.send(json_quil,
                              device="8Q-Agave",
                              user=None, password=None,
                              shots=shots, verbose=True)


def test_send_that_errors_are_caught(monkeypatch):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    def mocked_requests_get(*args, **kwargs):
        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url_status, status_url):
            return MockResponse({"state": True}, 200)

    def mocked_requests_post(*args, **kwargs):
        # Test that this error gets caught
        raise requests.exceptions.HTTPError

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    # Patch login data
    api_key = "test"
    user_id = "test@projectq.ch"
    monkeypatch.setitem(__builtins__, "input", lambda x: user_id)
    monkeypatch.setitem(__builtins__, "raw_input", lambda x: user_id)

    def user_api_key_input(prompt):
        if prompt == "Rigetti Forest API Key > ":
            return api_key

    monkeypatch.setattr("getpass.getpass", user_api_key_input)
    shots = 1
    json_quil = "my_json_quil"
    name = 'projectq_test'
    _rigetti_http_client.send(json_quil,
                          device="8Q-Agave",
                          user=None, password=None,
                          shots=shots, verbose=True)


def test_send_that_errors_are_caught2(monkeypatch):
    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url_status, status_url):
            return MockResponse({"state": True}, 200)

    def mocked_requests_post(*args, **kwargs):
        # Test that this error gets caught
        raise requests.exceptions.RequestException

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    # Patch login data
    api_key = "test"
    user_id = "test@projectq.ch"
    monkeypatch.setitem(__builtins__, "input", lambda x: user_id)
    monkeypatch.setitem(__builtins__, "raw_input", lambda x: user_id)

    def user_api_key_input(prompt):
        if prompt == "Rigetti Forest API Key > ":
            return api_key

    monkeypatch.setattr("getpass.getpass", user_api_key_input)
    shots = 1
    json_quil = "my_json_quil"
    name = 'projectq_test'
    _rigetti_http_client.send(json_quil,
                          device="8Q-Agave",
                          user=None, password=None,
                          shots=shots, verbose=True)


def test_send_that_errors_are_caught3(monkeypatch):
    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url_status, status_url):
            return MockResponse({"state": True}, 200)

    def mocked_requests_post(*args, **kwargs):
        # Test that this error gets caught
        raise KeyError

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    # Patch login data
    api_key = "test"
    user_id = "test@projectq.ch"
    monkeypatch.setitem(__builtins__, "input", lambda x: user_id)
    monkeypatch.setitem(__builtins__, "raw_input", lambda x: user_id)

    def user_api_key_input(prompt):
        if prompt == "Rigetti Forest API Key > ":
            return api_key

    monkeypatch.setattr("getpass.getpass", user_api_key_input)
    shots = 1
    json_quil = "my_json_quil"
    name = 'projectq_test'
    _rigetti_http_client.send(json_quil,
                          device="8Q-Agave",
                          user=None, password=None,
                          shots=shots, verbose=True)


def test_timeout_exception(monkeypatch):
    quils = {'quils': [{'quil': 'my quil'}]}
    json_quil = json.dumps(quils)
    tries = [0]

    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url, status_url):
            return MockResponse({"state": True}, 200)
        job_url = 'Jobs/{}'.format("123e")
        if args[0] == urljoin(_api_url, job_url):
            tries[0] += 1
            return MockResponse({"noquils": "not done"}, 200)

    def mocked_requests_post(*args, **kwargs):
        class MockRequest:
            def __init__(self, url=""):
                self.url = url

        class MockPostResponse:
            def __init__(self, json_data, text=" "):
                self.json_data = json_data
                self.text = text
                self.request = MockRequest()

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        login_url = 'users/login'
        if args[0] == urljoin(_api_url, login_url):
            return MockPostResponse({"userId": "1", "id": "12"})
        if args[0] == urljoin(_api_url, 'Jobs'):
            return MockPostResponse({"id": "123e"})

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    _rigetti_http_client.time.sleep = lambda x: x
    with pytest.raises(Exception) as excinfo:
        _rigetti_http_client.send(json_quil,
                              device="8Q-Agave",
                              user="test", password="test",
                              shots=1, verbose=False)
    assert "123e" in str(excinfo.value)  # check that job id is in exception
    assert tries[0] > 0


def test_retrieve_and_device_offline_exception(monkeypatch):
    quils = {'quils': [{'quil': 'my quil'}]}
    json_quil = json.dumps(quils)
    request_num = [0]

    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url, status_url) and request_num[0] < 2:
            return MockResponse({"state": True, "lengthQueue": 10}, 200)
        elif args[0] == urljoin(_api_url, status_url):
            return MockResponse({"state": False}, 200)
        job_url = 'Jobs/{}'.format("123e")
        if args[0] == urljoin(_api_url, job_url):
            request_num[0] += 1
            return MockResponse({"noquils": "not done"}, 200)

    def mocked_requests_post(*args, **kwargs):
        class MockRequest:
            def __init__(self, url=""):
                self.url = url

        class MockPostResponse:
            def __init__(self, json_data, text=" "):
                self.json_data = json_data
                self.text = text
                self.request = MockRequest()

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        login_url = 'users/login'
        if args[0] == urljoin(_api_url, login_url):
            return MockPostResponse({"userId": "1", "id": "12"})

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    _rigetti_http_client.time.sleep = lambda x: x
    with pytest.raises(_rigetti_http_client.DeviceOfflineError):
        _rigetti_http_client.retrieve(device="8Q-Agave",
                                  user="test", password="test",
                                  jobid="123e")


def test_retrieve(monkeypatch):
    quils = {'quils': [{'quil': 'my quil'}]}
    json_quil = json.dumps(quils)
    request_num = [0]

    def mocked_requests_get(*args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code):
                self.json_data = json_data
                self.status_code = status_code

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

        # Accessing status of device. Return online.
        status_url = 'devices'
        if args[0] == urljoin(_api_url, status_url):
            return MockResponse({"state": True}, 200)
        job_url = 'Jobs/{}'.format("123e")
        if args[0] == urljoin(_api_url, job_url) and request_num[0] < 1:
            request_num[0] += 1
            return MockResponse({"noquils": "not done"}, 200)
        elif args[0] == urljoin(_api_url, job_url):
            return MockResponse({"quils": [{'quil': 'quil',
                                            'result': 'correct'}]}, 200)

    def mocked_requests_post(*args, **kwargs):
        class MockRequest:
            def __init__(self, url=""):
                self.url = url

        class MockPostResponse:
            def __init__(self, json_data, text=" "):
                self.json_data = json_data
                self.text = text
                self.request = MockRequest()

            def json(self):
                return self.json_data

            def raise_for_status(self):
                pass

    monkeypatch.setattr("requests.get", mocked_requests_get)
    monkeypatch.setattr("requests.post", mocked_requests_post)
    _rigetti_http_client.time.sleep = lambda x: x
    res = _rigetti_http_client.retrieve(device="8Q-Agave",
                                    user_id="test", api_key="test",
                                    jobid="123e")
    assert res == 'correct'