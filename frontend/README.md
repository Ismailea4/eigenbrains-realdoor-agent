# 🎨 Frontend Directory (Lovable)

This folder is **OWNED BY Frontend Team** (Lovable).

We have strictly decoupled the frontend from the backend. Lovable generates exports here, and the backend engine makes no assumptions about its internal workings.

## 🔑 Critical File Isolation

To maintain this separation, the frontend must strictly adhere to these API contract rules:

### 1. Upload Protocol (The "Safe" Upload)

To protect the system from malicious uploads, all file uploads must follow this strict flow:

- **Endpoint:** `POST /api/v1/upload`
- **Body:** `multipart/form-data` containing `file`
- **Constraint:** The file is processed **ephemerally**. It is **never** saved to disk. Once the session ends (or the user clicks "Delete Session"), the file is instantly wiped from memory.
- **User Action Required:** Before using the uploaded document, the frontend **MUST** display the extracted data to the user and wait for a **human confirmation/correction** click. The backend will not proceed with any rule calculations until this confirmation is received.

### 2. Data Retrieval (The "Readiness" Status)

- **Endpoint:** `GET /api/v1/application-readiness/{session_id}`
- **Logic:** The frontend should poll this endpoint to check the status of uploaded documents.
- **Output:** Returns the current profile, confirmation status, and any detected gaps (e.g., "Missing pay stub").

### 3. Export / Download (The "Renter-Controlled" Packet)

- **Endpoint:** `POST /api/v1/export-packet/{session_id}`
- **Action:** Triggers the generation of the final application-readiness packet.
- **Constraint:** This is a renter-controlled action. The system should **never** generate this packet without explicit user consent.
- **Output:** Returns the packet (e.g., JSON/PDF) for immediate download.
