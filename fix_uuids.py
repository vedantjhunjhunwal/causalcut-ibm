import os
import glob
import re

TEST_SUITE_DIR = r"c:\Users\Niranjan\Desktop\THE HYD PROJECT\et-ai-hackathon\scenarios"
TARGET_UUID_1 = "00000000-0000-0000-0000-000000000001" # For steelforge-001
TARGET_UUID_2 = "00000000-0000-0000-0000-000000000002" # For northstar-alloys-plant-7

# Fix JSON files
for filepath in glob.glob(os.path.join(TEST_SUITE_DIR, "*.json")):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    content = content.replace("northstar-alloys-plant-7", TARGET_UUID_2)
    content = content.replace("steelforge-001", TARGET_UUID_1)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

# Fix python and js files
files_to_fix = [
    r"c:\Users\Niranjan\Desktop\THE HYD PROJECT\et-ai-hackathon\dashboard\src\components\ScenarioBuilder.jsx",
    r"c:\Users\Niranjan\Desktop\THE HYD PROJECT\et-ai-hackathon\app\schemas\scenario.py",
    r"c:\Users\Niranjan\Desktop\THE HYD PROJECT\et-ai-hackathon\app\db\repositories.py",
    r"c:\Users\Niranjan\Desktop\THE HYD PROJECT\et-ai-hackathon\app\api\v1\routes\scenario.py"
]

for filepath in files_to_fix:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        content = content.replace("northstar-alloys-plant-7", TARGET_UUID_2)
        content = content.replace("steelforge-001", TARGET_UUID_1)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

print("UUIDs replaced successfully.")
