# Load Testing

This directory contains the Locust load test setup for the CRM.

To run against a staging or production environment, start the Locust web interface:
`locust -f load/locustfile.py`

Then navigate to `http://localhost:8089` and enter the target host URL (e.g. `https://staging.wickhamroofing.app`) and the number of concurrent users to begin the load test.
