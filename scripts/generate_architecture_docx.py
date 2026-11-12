import os
import zipfile

def create_docx(filename="Phase_1_Architecture_Graph.docx"):
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:cs="Segoe UI"/>
        <w:sz w:val="22"/>
        <w:color w:val="1E293B"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
</w:styles>"""

    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <!-- Document Title -->
    <w:p>
      <w:pPr>
        <w:jc w:val="center"/>
        <w:spacing w:before="240" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:b/>
          <w:sz w:val="48"/>
          <w:color w:val="0F172A"/>
        </w:rPr>
        <w:t>Knowra / OmniRAG — Phase 1 Architecture Graph</w:t>
      </w:r>
    </w:p>

    <!-- Subtitle -->
    <w:p>
      <w:pPr>
        <w:jc w:val="center"/>
        <w:spacing w:before="0" w:after="360"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:sz w:val="24"/>
          <w:color w:val="64748B"/>
        </w:rPr>
        <w:t>Local Chat Gateway — Directed Module Dependency &amp; Data Flow Graph</w:t>
      </w:r>
    </w:p>

    <!-- Section Heading: Overview -->
    <w:p>
      <w:pPr>
        <w:spacing w:before="280" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:b/>
          <w:sz w:val="32"/>
          <w:color w:val="1E3A8A"/>
        </w:rPr>
        <w:t>1. Architectural Overview</w:t>
      </w:r>
    </w:p>

    <w:p>
      <w:pPr>
        <w:spacing w:before="0" w:after="160"/>
      </w:pPr>
      <w:r>
        <w:t>Phase 1 establishes the baseline Local Chat Gateway. It connects the Next.js React frontend to the FastAPI backend, utilizing an abstract LLM Gateway to stream generated tokens from a local Ollama model (e.g. Qwen / Llama) via Server-Sent Events (SSE), alongside JWT-authenticated sessions and persistent chat history in PostgreSQL.</w:t>
      </w:r>
    </w:p>

    <!-- Section Heading: Graph Diagram -->
    <w:p>
      <w:pPr>
        <w:spacing w:before="280" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:b/>
          <w:sz w:val="32"/>
          <w:color w:val="1E3A8A"/>
        </w:rPr>
        <w:t>2. Phase 1 Directed Module Graph (ASCII Topology)</w:t>
      </w:r>
    </w:p>

    <!-- Graph ASCII Box -->
    <w:p>
      <w:pPr>
        <w:pBdr>
          <w:top w:val="single" w:sz="6" w:space="4" w:color="CBD5E1"/>
          <w:left w:val="single" w:sz="6" w:space="4" w:color="CBD5E1"/>
          <w:bottom w:val="single" w:sz="6" w:space="4" w:color="CBD5E1"/>
          <w:right w:val="single" w:sz="6" w:space="4" w:color="CBD5E1"/>
        </w:pBdr>
        <w:shd w:val="clear" w:color="auto" w:fill="F8FAFC"/>
        <w:spacing w:before="120" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>
          <w:sz w:val="17"/>
          <w:color w:val="0F172A"/>
        </w:rPr>
        <w:t xml:space="preserve">[USER / BROWSER]
       │
       ├─────────────────────────────────┐
       ▼ (Interacts)                     ▼ (Authenticates)
[frontend: ChatPage]              [frontend: LoginPage]
  (src/app/(dashboard)/chat)        (src/app/(auth)/login)
       │                                 │
       ├──────────────┐                  │ POST /api/v1/auth/*
       ▼              ▼                  ▼
[ChatComposer]  [MessageList]     [backend: api/routes/auth.py]
       │              ▲                  │             │
       ▼ Trigger      │ Render           ▼ Validate    ▼ Persist
[useChatStream]───────┼───────────► [core/security.py] [models/user.py]
 (SSE Client Hook)    │                  ▲             │
       │              │                  │ Verify      ▼
       │ POST /chat   │                  │          [PostgreSQL]
       ▼ (SSE Stream) │                  │             ▲
[backend: api/routes/chat.py]            │             │
       │                                 │             │
       ├─────────────────────────────────┘             │
       ├────────────────────────────────────────► [models/chat.py]
       │
       ▼ Dispatch Prompt
[backend: llm/gateway.py (LLMGateway)]
       │
       ▼ Resolves Contract
[backend: llm/base.py (LLMProvider Interface)]
       ▲
       │ Implements
[backend: llm/ollama_provider.py (OllamaProvider)]
       │
       ▼ HTTP /api/chat (Stream chunks)
[infra: Ollama Service (Port 11434)]</w:t>
      </w:r>
    </w:p>

    <!-- Section Heading: Graph Nodes & Modules -->
    <w:p>
      <w:pPr>
        <w:spacing w:before="320" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:b/>
          <w:sz w:val="32"/>
          <w:color w:val="1E3A8A"/>
        </w:rPr>
        <w:t>3. Graph Nodes Specification</w:t>
      </w:r>
    </w:p>

    <!-- Table of Graph Nodes -->
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="9600" w:type="dxa"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:left w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
          <w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
        </w:tblBorders>
      </w:tblPr>

      <!-- Row Header -->
      <w:tr>
        <w:trPr><w:tblHeader/></w:trPr>
        <w:tc>
          <w:tcPr><w:tcW w:w="2000" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Node Name</w:t></w:r></w:p>
        </w:tc>
        <w:tc>
          <w:tcPr><w:tcW w:w="3200" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Module File Path</w:t></w:r></w:p>
        </w:tc>
        <w:tc>
          <w:tcPr><w:tcW w:w="4400" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Role &amp; Responsibilities</w:t></w:r></w:p>
        </w:tc>
      </w:tr>

      <!-- Node 1 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>F_Auth</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>frontend/src/app/(auth)/login/page.tsx</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>User sign-in view collecting credentials and storing JWT tokens.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 2 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>F_Chat</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>frontend/src/app/(dashboard)/chat/page.tsx</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Main interactive chat interface mounting composer and message log.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 3 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>F_Hook</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>frontend/src/lib/hooks/useChatStream.ts</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Streams SSE events from API, buffering and updating token chunks.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 4 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>B_Main</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/main.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>FastAPI application factory, CORS origins, router assembly.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 5 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>B_Sec</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/core/security.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Password hashing, JWT decoding, authentication dependencies.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 6 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>R_Auth</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/api/routes/auth.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Routes for /register, /login, and /refresh token handlers.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 7 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>R_Chat</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/api/routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Chat endpoint providing run_id tagging, persistence, and SSE generator.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 8 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>M_User</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/models/user.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>SQLAlchemy schema: User, Organization, Workspace.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 9 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>M_Chat</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/models/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>SQLAlchemy schema: Conversation and Message entities.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 10 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>L_Gate</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/llm/gateway.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Model router mapping roles ('fast', 'strong', etc.) to configured providers.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 11 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>L_Base</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/llm/base.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Abstract Base Class defining generate() and stream_chat() contracts.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 12 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>L_Ollama</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>backend/app/llm/ollama_provider.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Concrete Ollama HTTP client consuming local streaming model responses.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 13 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>I_Ollama</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>Docker Container: ollama (Port 11434)</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Hosts local LLM weights (Qwen3 / Llama) with GPU/CPU inference.</w:t></w:r></w:p></w:tc>
      </w:tr>

      <!-- Node 14 -->
      <w:tr>
        <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>I_PG</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t>Docker Container: postgres:16 (Port 5432)</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Relational database housing user identity, auth credentials, and chats.</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>

    <!-- Section Heading: Graph Directed Edges -->
    <w:p>
      <w:pPr>
        <w:spacing w:before="320" w:after="120"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:b/>
          <w:sz w:val="32"/>
          <w:color w:val="1E3A8A"/>
        </w:rPr>
        <w:t>4. Directed Graph Edges (Data &amp; Control Flow)</w:t>
      </w:r>
    </w:p>

    <!-- Table of Directed Edges -->
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="9600" w:type="dxa"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:left w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>
          <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
          <w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>
        </w:tblBorders>
      </w:tblPr>

      <!-- Row Header -->
      <w:tr>
        <w:trPr><w:tblHeader/></w:trPr>
        <w:tc>
          <w:tcPr><w:tcW w:w="2400" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Source Node</w:t></w:r></w:p>
        </w:tc>
        <w:tc>
          <w:tcPr><w:tcW w:w="2400" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Target Node</w:t></w:r></w:p>
        </w:tc>
        <w:tc>
          <w:tcPr><w:tcW w:w="4800" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="0F172A"/></w:tcPr>
          <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>Protocol / Action</w:t></w:r></w:p>
        </w:tc>
      </w:tr>

      <!-- Edge 1 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>User / Browser</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>frontend: LoginPage</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Submits email / password form</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 2 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>frontend: LoginPage</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: routes/auth.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>HTTP POST /api/v1/auth/login</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 3 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: routes/auth.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: core/security.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Verifies password hash &amp; issues JWT token</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 4 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: routes/auth.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: models/user.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>SQL query / update User entity in PostgreSQL</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 5 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>frontend: ChatComposer</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>frontend: useChatStream</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Invokes sendMessage(prompt, conversationId)</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 6 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>frontend: useChatStream</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>HTTP POST /api/v1/chat (Authorization: Bearer JWT)</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 7 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: models/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Stores incoming user message in DB</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 8 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: llm/gateway.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Resolves 'fast' role provider and forwards prompt</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 9 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: llm/gateway.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: llm/ollama_provider.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Calls stream_chat(messages, model)</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 10 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: llm/ollama_provider.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>infra: Ollama Service</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>HTTP POST http://ollama:11434/api/chat</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 11 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>infra: Ollama Service</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>backend: routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Streams raw token chunks via AsyncIterator</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 12 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>backend: routes/chat.py</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>frontend: useChatStream</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Server-Sent Events (SSE: data: {"token": "..."})</w:t></w:r></w:p></w:tc>
      </w:tr>
      <!-- Edge 13 -->
      <w:tr>
        <w:tc><w:p><w:r><w:t>frontend: useChatStream</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>frontend: MessageList</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Appends tokens to active assistant message in UI</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:pPr><w:spacing w:before="360" w:after="120"/></w:pPr></w:p>
  </w:body>
</w:document>"""

    with zipfile.ZipFile(filename, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/document.xml", document)

    print(f"Created {filename} successfully.")

if __name__ == "__main__":
    output_path = os.path.join(os.path.dirname(__file__), "..", "Phase_1_Architecture_Graph.docx")
    create_docx(os.path.abspath(output_path))
