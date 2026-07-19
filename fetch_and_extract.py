import os
import re
from bs4 import BeautifulSoup

def clean_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.decompose()
    
    content = soup.find('div', class_='field--name-field-page-content')
    if content:
        text_blocks = []
        for p in content.find_all(['p', 'span', 'h2', 'h3']):
            t = p.get_text(strip=True)
            if t:
                text_blocks.append(t)
        
        full_text = '\n'.join(text_blocks)
        return full_text[:2500]
    
    # Generic extraction
    return soup.get_text(separator='\n', strip=True)

# Fallback for broken Factories Act files
FACTORIES_ACT_TEXTS = {
    "Section 36": "36. Precautions against dangerous fumes, gases, etc.—(1) No person shall be required or allowed to enter any chamber, tank, vat, pit, pipe, flue or other confined space in any factory in which any gas, fume, vapour or dust is likely to be present to such an extent as to involve risk to persons being overcome thereby, unless it is provided with a manhole of adequate size or other effective means of egress.\n(2) No person shall be required or allowed to enter any such confined space as is referred to in sub-section (1), until all practicable measures have been taken to remove any gas, fume, vapour or dust, which may be present so as to bring its level within the permissible limits and to prevent any ingress of such gas, fume, vapour or dust and unless—(a) a certificate in writing has been given by a competent person, based on a test carried out by himself, that the space is reasonably free from dangerous gas, fume, vapour or dust; or (b) such person is wearing suitable breathing apparatus and a belt securely attached to a rope the free end of which is held by a person outside the confined space.",
    "Section 41": "41. Power to make rules to supplement this Chapter.—The State Government may make rules requiring the provision in any factory or in any class or description of factories of such further devices and measures for securing the safety of persons employed therein as it may deem necessary.",
    "Section 37": "37. Explosive or inflammable dust, gas, etc.—(1) Where in any factory any manufacturing process produces dust, gas, fume or vapour of such character and to such extent as to be likely to explode on ignition, all practicable measures shall be taken to prevent any such explosion by—(a) effective enclosure of the plant or machinery used in the process; (b) removal or prevention of the accumulation of such dust, gas, fume or vapour; (c) exclusion or effective enclosure of all possible sources of ignition.",
    "Section 38": "38. Precautions in case of fire.—(1) In every factory, all practicable measures shall be taken to prevent outbreak of fire and its spread, both internally and externally, and to provide and maintain—(a) safe means of escape for all persons in the event of a fire, and (b) the necessary equipment and facilities for extinguishing fire.\n(2) Effective measures shall be taken to ensure that in every factory all the workers are familiar with the means of escape in case of fire and have been adequately trained in the routine to be followed in such cases.",
    "Section 41A": "41A. Constitution of Site Appraisal Committees.—(1) The State Government may, for purposes of advising it to consider applications for grant of permission for the initial location of a factory involving a hazardous process or for the expansion of any such factory, appoint a Site Appraisal Committee.\n(2) The Site Appraisal Committee shall examine an application for the establishment of a factory involving hazardous process and make its recommendation to the State Government within a period of ninety days of the receipt of such application in the prescribed form.",
    "Section 41B": "41B. Compulsory disclosure of information by the occupier.—(1) The occupier of every factory involving a hazardous process shall disclose in the manner prescribed all information regarding dangers, including health hazards and the measures to overcome such hazards arising from the exposure to or handling of the materials or substances in the manufacture, transportation, storage and other processes, to the workers employed in the factory, the Chief Inspector, the local authority within whose jurisdiction the factory is situate and the general public in the vicinity.\n(2) The occupier shall, at the time of registering the factory involving a hazardous process, lay down a detailed policy with respect to the health and safety of the workers employed therein.",
    "Section 41C": "41C. Specific responsibility of the occupier in relation to hazardous processes.—Every occupier of a factory involving any hazardous process shall—(a) maintain accurate and up-to-date health records or, as the case may be, medical records, of the workers in the factory who are exposed to any chemical, toxic or any other harmful substances which are manufactured, stored, handled or transported and such records shall be accessible to the workers subject to such conditions as may be prescribed; (b) appoint persons who possess qualifications and experience in handling hazardous substances.",
    "Section 41F": "41F. Maximum permissible threshold limits of exposure of chemical and toxic substances.—(1) The maximum permissible threshold limits of exposure of chemical and toxic substances in manufacturing processes (whether hazardous or otherwise) in any factory shall be of the value indicated in the Second Schedule.\n(2) The Central Government may, at any time, by notification in the Official Gazette, make suitable changes in the said Schedule.",
    "Section 41H": "41H. Right of workers to warn about imminent danger.—(1) Where the workers employed in any factory engaged in a hazardous process have reasonable apprehension that there is a likelihood of imminent danger to their lives or health due to any accident, they may bring the same to the notice of the occupier, agent, manager or any other person who is incharge of the factory or the process concerned directly or through their representatives in the Safety Committee and simultaneously bring the same to the notice of the Inspector.\n(2) It shall be the duty of such occupier, agent, manager or the person incharge of the factory or process, on receipt of the notice under sub-section (1), to take immediate remedial action if he is satisfied about the existence of such imminent danger."
}

def main():
    osha_files = [
        ("1910.119 Process Safety Management", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\99\content.md"),
        ("1910.146 Confined Spaces", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\100\content.md"),
        ("1910.252 Hot Work/Welding", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\101\content.md"),
        ("1910.132 PPE", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\111\content.md")
    ]
    
    factories_files = [
        ("Section 36", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\109\content.md"),
        ("Section 41", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\110\content.md"),
        ("Section 37", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\117\content.md"),
        ("Section 38", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\118\content.md"),
        ("Section 41A", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\119\content.md"),
        ("Section 41B", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\121\content.md"),
        ("Section 41C", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\122\content.md"),
        ("Section 41F", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\123\content.md"),
        ("Section 41H", r"C:\Users\Niranjan\.gemini\antigravity\brain\f22f7643-0104-46e4-8c8f-e64d0a411c8b\.system_generated\steps\124\content.md"),
    ]

    out_dir = r"c:\Users\Niranjan\Desktop\ET AI HACK\et-ai-Hackathon-\regulatory_docs"
    os.makedirs(out_dir, exist_ok=True)
    
    # Process OSHA
    osha_data = []
    for i, (title, path) in enumerate(osha_files):
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if content.startswith("Title: Live Content"):
            parts = content.split('---', 1)
            if len(parts) > 1:
                content = parts[1]
                
        text = clean_text(content)
        
        doc = {
            "doc_id": f"OSHA_{title.split()[0]}",
            "source_type": "oisd_standard",
            "title": f"OSHA {title}",
            "text": text
        }
        osha_data.append(doc)
        
    with open(os.path.join(out_dir, "osha_standards.py"), "w", encoding='utf-8') as f:
        f.write("OSHA_STANDARDS = [\n")
        for doc in osha_data:
            f.write(f"    {repr(doc)},\n")
        f.write("]\n")

    # Process Factories Act
    factories_data = []
    for i, (title, path) in enumerate(factories_files):
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if content.startswith("Title: Live Content"):
            parts = content.split('---', 1)
            if len(parts) > 1:
                content = parts[1]
                
        text = clean_text(content)
        # Check if the extracted text is just an error or too short
        if "Invalid URL" in text or len(text.strip()) < 50:
            text = FACTORIES_ACT_TEXTS.get(title, text)
        
        doc = {
            "doc_id": f"FA_SEC_{title.split()[-1]}",
            "source_type": "factories_act",
            "title": f"Factories Act 1948 - {title}",
            "text": text
        }
        factories_data.append(doc)
        
    with open(os.path.join(out_dir, "factories_act.py"), "w", encoding='utf-8') as f:
        f.write("FACTORIES_ACT_DOCS = [\n")
        for doc in factories_data:
            f.write(f"    {repr(doc)},\n")
        f.write("]\n")
        
    # Update __init__.py
    init_path = os.path.join(out_dir, "__init__.py")
    with open(init_path, "w", encoding='utf-8') as f:
        f.write("from .osha_standards import OSHA_STANDARDS\n")
        f.write("from .factories_act import FACTORIES_ACT_DOCS\n")

if __name__ == "__main__":
    main()
