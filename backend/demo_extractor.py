import sys
from pathlib import Path
from pprint import pprint

# Ensure the 'app' module can be found
sys.path.insert(0, str(Path(__file__).parent))

try:
    from app.services.extractor import extract_document
except ImportError as e:
    print(f"ImportError: {e}. Ensure dependencies like 'pymupdf' and 'pydantic' are installed.")
    sys.exit(1)

pdf_path = r"C:\Users\PC\Desktop\Hacknation 6th\eigenbrains-realdoor-agent\data\realdoor-hackathon-starter-pack\synthetic_documents\documents\hh-001_d02_pay_stub.pdf"

print(f"Extracting data from: {Path(pdf_path).name}...\n")
try:
    # Call the extractor function.
    result = extract_document(pdf_path, enable_ocr=True)
    
    print("=== EXTRACTED FIELDS ===")
    for field in result.fields:
        print(f"[{field.confidence*100:.1f}% Confidence] {field.field.value}: {field.value}")
        print(f"    -> Source: Page {field.evidence.page}, Bounding Box {field.evidence.bbox}")
    
    print("\n=== STRUCTURED PYDANTIC MODEL ===")
    pprint(result.structured_data.model_dump() if result.structured_data else None)
    
    if result.warnings:
        print("\n=== WARNINGS ===")
        for w in result.warnings:
            print("-", w)
            
except Exception as e:
    print("Error during extraction:", e)
