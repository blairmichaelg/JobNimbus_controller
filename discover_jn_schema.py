import asyncio
import json
import re
from pathlib import Path

from app.services.jobnimbus_client import JobNimbusClient
from app.services.ai_service import AIService
from app.config import get_settings

TARGET_MAPPING_GOALS = """
- Insurance Details: Claim #, Date of Loss, Insurance Company, Policy #, Adjuster Name & Phone, Deductible Amount, RCV, ACV, Recoverable Depreciation, Contract Signed?
- Field Inspection: Decking Condition / Soft Spots, Inspection Completed, Shingle Manufacturer, Roof Age, Shingle Color, Roof Type, Gated Community, Gate Code, Damage Type, Code Upgrades Needed, Total Squares (Roofing), Roof Pitch
- System Links: EagleView / HOVER Order ID, Restoration AI Link
"""

async def main():
    settings = get_settings()
    
    # 1. Fetch data
    print("Fetching jobs from JobNimbus...")
    async with JobNimbusClient(settings) as jn_client:
        try:
            response = await jn_client._client.get("/jobs", params={"size": 50})
            response.raise_for_status()
            jobs_data = response.json().get("results", [])
            print(f"Fetched {len(jobs_data)} jobs.")
        except Exception as e:
            print(f"API failed ({str(e)}). Falling back to mock data for demonstration.")
            jobs_data = [
                {
                    "cf_string_1": "State Farm",
                    "cf_string_2": "CLA-99887",
                    "cf_date_1": "2023-10-01",
                    "cf_number_1": 1000.0,
                    "cf_number_2": 15000.0,
                    "cf_number_3": 10000.0,
                    "cf_string_3": "Bob Smith 555-1234",
                    "cf_boolean_1": True,
                    "cf_string_4": "Rotten decking in valley",
                    "cf_date_2": "2023-10-05",
                    "cf_string_5": "Owens Corning",
                    "cf_string_6": "15 years",
                    "cf_string_7": "Onyx Black",
                    "cf_string_8": "Architectural",
                    "cf_boolean_2": True,
                    "cf_string_9": "1234#",
                    "cf_string_10": "Hail",
                    "cf_boolean_3": True,
                    "cf_number_4": 35.5,
                    "cf_string_11": "6/12",
                    "cf_string_12": "EV-999000",
                    "cf_string_13": "https://restoration.ai/link"
                }
            ]

    # 2. Parse cf_ fields
    cf_map = {}
    for job in jobs_data:
        for key, value in job.items():
            if key.startswith("cf_") and value is not None and value != "":
                if key not in cf_map:
                    cf_map[key] = set()
                if len(cf_map[key]) < 5:
                    # Convert dicts/lists to string if any
                    cf_map[key].add(str(value))
    
    # Convert sets to lists
    cf_samples = {k: list(v) for k, v in cf_map.items()}
    print(f"Found {len(cf_samples)} custom fields.")
    
    # 3. AI Inference
    ai = AIService()
    prompt = f"""
You are a data engineer analyzing custom fields from a JobNimbus CRM database.
Below is a dictionary of obfuscated custom keys (e.g., 'cf_string_1') mapped to a sample of 3-5 real values found in the database.

Database Samples:
{json.dumps(cf_samples, indent=2)}

Target Concepts to Map To:
{TARGET_MAPPING_GOALS}

Analyze the footprints of the samples and map the obfuscated keys to a clean, lowercase, snake_case version of the target concept (e.g. 'claim_number', 'decking_condition', 'total_squares', 'rcv', 'acv'). Do NOT map keys that don't match our targets.
You MUST output a valid JSON dictionary ONLY, mapping the 'cf_' key to the snake_case human-readable string.

Example Output:
{{
  "cf_string_1": "insurance_company",
  "cf_date_2": "date_of_loss",
  "cf_number_5": "deductible_amount"
}}
"""

    print("Sending to Gemini for analysis...")
    response = await asyncio.to_thread(ai.model.generate_content, prompt)
    ai_mapping_text = response.text
    
    # Strip markdown if any
    if ai_mapping_text.startswith("```json"):
        ai_mapping_text = ai_mapping_text.replace("```json", "").replace("```", "").strip()
    elif ai_mapping_text.startswith("```"):
        ai_mapping_text = ai_mapping_text.replace("```", "").strip()
        
    final_mapping = json.loads(ai_mapping_text)
    print(f"AI mapped {len(final_mapping)} fields successfully:")
    print(json.dumps(final_mapping, indent=2))
    
    # 4. Automated Code Injection
    field_mapper_path = Path("app/core/field_mapper.py")
    content = field_mapper_path.read_text()
    
    mapping_str = json.dumps(final_mapping, indent=4)
    
    # Replace DEFAULT_MAPPING
    # Use regex to replace the dictionary block
    pattern = re.compile(r"DEFAULT_MAPPING\s*=\s*\{.*?}", re.DOTALL)
    new_content = pattern.sub(f"DEFAULT_MAPPING = {mapping_str}", content)
    
    field_mapper_path.write_text(new_content)
    print("Injected new mapping into app/core/field_mapper.py")

if __name__ == "__main__":
    asyncio.run(main())
