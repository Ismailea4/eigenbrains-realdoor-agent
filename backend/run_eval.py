import sys
import json
import os
from pathlib import Path

# Ensure the 'app' module can be found
sys.path.insert(0, str(Path(__file__).parent))

try:
    from app.services.extractor import extract_document
except ImportError as e:
    print(f"ImportError: {e}. Ensure dependencies are installed.")
    sys.exit(1)

# File paths
base_dir = Path(r"C:\Users\PC\Desktop\Hacknation 6th\eigenbrains-realdoor-agent")
documents_dir = base_dir / "data" / "realdoor-hackathon-starter-pack" / "synthetic_documents" / "documents"

pay_stub_path = documents_dir / "hh-003_d02_pay_stub.pdf"
benefit_letter_path = documents_dir / "hh-003_d04_benefit_letter.pdf"

# Output directory
output_dir = base_dir / "backend" / "extraction_results"
output_dir.mkdir(parents=True, exist_ok=True)

files_to_process = [pay_stub_path, benefit_letter_path]

# We need a custom JSON encoder to handle Enum types and other non-serializable objects from Pydantic models
def custom_serializer(obj):
    from enum import Enum
    if isinstance(obj, Enum):
        return obj.value
    return str(obj)

for file_path in files_to_process:
    print(f"Processing {file_path.name}...")
    try:
        # We set enable_ocr=True as per our previous fix
        result = extract_document(file_path, enable_ocr=True)
        
        output_data = {
            "document_id": result.document_id,
            "document_type": result.document_type.value if result.document_type else None,
            "page_count": result.page_count,
            "status": result.status.value if result.status else None,
            "structured_data": result.structured_data.model_dump() if result.structured_data else None,
            "warnings": result.warnings
        }
        
        output_file = output_dir / f"{file_path.stem}_result.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, default=custom_serializer)
            
        print(f"Success: Saved results to {output_file.name}")
        
    except Exception as e:
        print(f"Error processing {file_path.name}: {e}")

print(f"\nAll extractions complete. Results are saved in {output_dir}")
