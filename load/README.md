# Load Testing

> [!WARNING]
> Do not run this against production without Michael's explicit approval — this creates real test leads and hits real authenticated endpoints repeatedly.

This directory contains the Locust load test setup for the CRM.

Before running against staging or production, set the real admin PIN:
`export LOAD_TEST_ADMIN_PIN=<actual_pin_for_target_env>`
Never hardcode real PINs into this file or commit them.

To run against a staging or production environment, start the Locust web interface:
`locust -f load/locustfile.py`

Then navigate to `http://localhost:8089` and enter the target host URL (e.g. `https://staging.wickhamroofing.app`) and the number of concurrent users to begin the load test.
