from locust import HttpUser, task, between

class CRMUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Authenticate simulating office dashboard load (similar to test_ui_contracts.py setup)
        # Using pin 9999 for admin
        response = self.client.post("/auth/login", data={"pin": "9999", "redirect_url": "/"}, allow_redirects=False)
        self.auth_token = response.cookies.get("auth_token", "")

    @task(3)
    def health_check(self):
        """Baseline - should always be fast and cheap"""
        self.client.get("/health")

    @task(2)
    def view_admin_dashboard(self):
        """Simulates office dashboard load"""
        self.client.get("/admin")

    @task(1)
    def create_lead(self):
        """Simulates a canvasser creating a new lead"""
        payload = {
            "homeowner_name": "Test Homeowner",
            "address_line1": "123 Main St",
            "city": "Testville",
            "state": "TS",
            "postal_code": "12345",
            "phone": "555-555-5555"
        }
        self.client.post("/api/field/jobs", json=payload)
