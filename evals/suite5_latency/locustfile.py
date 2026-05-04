"""
Locust load test for the Smart Home AI gateway.
"""
import uuid
from locust import HttpUser, task, between

PLAIN_CHAT_MESSAGES = [
    "Hello, what can you help me with?",
    "What is Home Assistant?",
    "Can you explain what MQTT is?",
    "How many smart home protocols exist?",
    "What is a Zigbee coordinator?",
]

RAG_MESSAGES = [
    "How do I pair a Zigbee bulb in Home Assistant?",
    "What is the difference between ZHA and Zigbee2MQTT?",
    "How do I set up an MQTT broker in Home Assistant?",
    "How do I create an automation that runs at sunset?",
    "How do I back up my Home Assistant configuration?",
]

class ChatUser(HttpUser):
    wait_time = between(1, 3)
    _msg_index = 0
    _rag_index = 0

    @task(1)
    def send_plain_chat(self):
        session_id = str(uuid.uuid4())
        msg = PLAIN_CHAT_MESSAGES[self._msg_index % len(PLAIN_CHAT_MESSAGES)]
        self._msg_index += 1
        with self.client.post(
            "/chat",
            json={"session_id": session_id, "message": msg, "history": []},
            name="/chat [plain]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def send_rag_chat(self):
        session_id = str(uuid.uuid4())
        msg = RAG_MESSAGES[self._rag_index % len(RAG_MESSAGES)]
        self._rag_index += 1
        with self.client.post(
            "/chat",
            json={"session_id": session_id, "message": msg, "history": []},
            name="/chat [rag]",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
