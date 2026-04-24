"""
AEGIS — AI Support Automation Engine
Production-grade standalone Streamlit app.

Zero infrastructure. Deploy to Streamlit Cloud with only a Groq API key.

Stack:
  - Groq (Llama 3.3 70B) — free LLM
  - HuggingFace all-MiniLM-L6-v2 — free local embeddings
  - FAISS — vector search
  - SQLite — persistence
  - Streamlit — UI and hosting

Local:
    pip install -r requirements.txt
    echo 'GROQ_API_KEY = "gsk-..."' > .streamlit/secrets.toml
    streamlit run standalone.py

Cloud: push to GitHub, connect at share.streamlit.io, add GROQ_API_KEY secret.
"""

import os
import re
import csv
import time
import sqlite3
import hashlib
import io
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

st.set_page_config(
    page_title="AEGIS · AI Support Automation",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }

section[data-testid="stSidebar"] { width: 270px !important; min-width: 270px !important; }
section[data-testid="stSidebar"] > div:first-child { width: 270px !important; }

.chat-user {
    background: #1F4E79; color: white; padding: 10px 14px;
    border-radius: 12px 12px 2px 12px; display: inline-block; max-width: 82%; margin: 4px 0;
}
.chat-bot {
    background: #f0f4f8; color: #1a1a1a; padding: 10px 14px;
    border-radius: 12px 12px 12px 2px; display: inline-block; max-width: 82%; margin: 4px 0;
}
.chat-escalate {
    background: #fff3cd; border-left: 4px solid #ffc107;
    padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 4px 0;
}
.source-chip {
    display: inline-block; background: #e8f0fe; color: #1967d2;
    padding: 2px 8px; border-radius: 12px; font-size: 11px; margin: 2px;
}
.sla-ok   { color: #0F6E56; font-weight: bold; }
.sla-warn { color: #BA7517; font-weight: bold; }
.sla-breach { color: #A32D2D; font-weight: bold; }
.kpi-card {
    background: white; border: 1px solid #e0e0e0; border-radius: 10px;
    padding: 16px 20px; text-align: center;
}
.alert-banner {
    background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px;
    padding: 10px 16px; margin-bottom: 8px;
}
.insight-card {
    background: #E6F1FB; border-left: 4px solid #1F4E79;
    padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 6px 0;
}
</style>
""", unsafe_allow_html=True)


# ── API key ───────────────────────────────────────────────────────────────────

def get_groq_key() -> str:
    try:
        k = st.secrets.get("GROQ_API_KEY", "")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", st.session_state.get("groq_key", ""))


# ── Database ──────────────────────────────────────────────────────────────────

DB_PATH = Path("data/aegis.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72, "P4": 168}


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tickets (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        subject             TEXT,
        body                TEXT,
        intent              TEXT,
        priority            TEXT DEFAULT 'P3',
        team                TEXT,
        status              TEXT DEFAULT 'open',
        source              TEXT DEFAULT 'manual',
        confidence          REAL,
        escalation_reason   TEXT,
        tier                TEXT DEFAULT 'standard',
        csat                INTEGER,
        resolution_note     TEXT,
        assigned_to         TEXT,
        created_at          TEXT DEFAULT (datetime('now')),
        updated_at          TEXT DEFAULT (datetime('now')),
        resolved_at         TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        intent      TEXT,
        confidence  REAL,
        action      TEXT,
        latency_ms  INTEGER,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS email_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender      TEXT,
        subject     TEXT,
        intent      TEXT,
        action      TEXT,
        template    TEXT,
        sentiment   TEXT DEFAULT 'neutral',
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS kb_gaps (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        query       TEXT,
        intent      TEXT,
        confidence  REAL,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS csat_ratings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id   INTEGER,
        session_id  TEXT,
        rating      INTEGER,
        comment     TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    """)
    c.commit()
    c.close()


# ── Intent classifier ─────────────────────────────────────────────────────────

PRIORITY_MAP = {
    "backup_failure": "P1", "restore_request": "P1",
    "access_issue": "P2", "performance": "P2", "licensing": "P2",
    "installation": "P3", "configuration": "P3",
    "billing": "P2", "general_inquiry": "P3",
    "feature_request": "P4", "_escalate": "P1", "_greeting": "P3",
}
TEAM_MAP = {
    "backup_failure": "backup_team", "restore_request": "backup_team",
    "access_issue": "security_team", "performance": "platform_sre",
    "licensing": "license_team", "installation": "ops_team",
    "configuration": "ops_team", "billing": "billing_team",
    "feature_request": "product_team", "general_inquiry": "general_support",
    "_escalate": "senior_support", "_greeting": "general_support",
}

ESCALATE_PATTERNS = [
    r"speak.{0,15}(human|agent|person|representative)",
    r"(real|live|actual).{0,10}(person|agent|human)",
    r"(lawsuit|legal|lawyer|attorney|sue)",
    r"data loss|lost.{0,8}(all|my) data|everything.{0,5}gone",
    r"production.{0,10}(down|offline|not working)",
    r"critical outage|all backups failed",
]

RULE_PATTERNS = [
    (r"backup.{0,30}(fail|error|stuck|not running|abort)", "backup_failure", 0.92),
    (r"(job|task).{0,15}(fail|error|status code)",          "backup_failure", 0.88),
    (r"CV-\d{4,6}",                                          "backup_failure", 0.93),
    (r"(restore|recover|recovery|rollback)",                 "restore_request", 0.91),
    (r"(cleanroom|disaster recovery|DR test)",               "restore_request", 0.88),
    (r"(licens|expired|activation|serial key|renewal)",      "licensing",       0.91),
    (r"(login|password|sign.?in|access denied|locked out|mfa|2fa|sso)", "access_issue", 0.90),
    (r"(slow|performance|latency|timeout|hung|freezing|bottleneck)", "performance", 0.86),
    (r"(install|uninstall|upgrade|downgrade|deploy agent)",  "installation",    0.85),
    (r"(configure|setup|config|setting|wizard|onboard)",     "configuration",   0.83),
    (r"(invoice|charge|payment|subscription|billing|refund)","billing",         0.90),
    (r"(feature request|enhancement|suggestion|roadmap)",    "feature_request", 0.87),
]

GREETINGS = {
    "hi", "hey", "hello", "hiya", "howdy", "sup", "yo", "ok", "okay",
    "cool", "great", "got it", "bye", "goodbye", "thanks", "thank you",
    "good morning", "good afternoon", "good evening", "thx", "ty",
}


def classify(text: str) -> tuple[str, bool]:
    t = text.lower().strip()

    if t in GREETINGS or (len(t.split()) <= 3 and any(g in t for g in GREETINGS)):
        return "_greeting", False

    for pat in ESCALATE_PATTERNS:
        if re.search(pat, t):
            return "_escalate", True

    for pattern, intent, _ in RULE_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            return intent, False

    return "general_inquiry", False


def get_confidence_from_text(text: str) -> float:
    t = text.lower()
    for pattern, _, confidence in RULE_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            return confidence
    return 0.5


# ── Knowledge base documents ──────────────────────────────────────────────────

KB_DOCS = {
    "backup_errors.txt": """# Commvault Backup Error Reference

CV-12345: Network connectivity timeout between client and CommServe.
Fix: Check firewall rules. Ensure port 8400 is open between client and CommServe.
Verify DNS resolution is working correctly for the CommServe hostname.
Run ping and telnet tests from the client to CommServe on port 8400.

CV-8892: Insufficient disk space on the MediaAgent.
Fix: Free up space on the MediaAgent storage volume.
Add a new storage pool in Command Center under Storage > Disk Storage.
Check disk usage with the Storage Resources report.

CV-9999: Agent version mismatch after software upgrade.
Fix: Push a fresh agent update from Command Center > Administration > Update Software.
Select the affected client and run Update Software.
Restart Commvault services after the update completes.

CV-4521: Exchange Web Services (EWS) connection failure.
Fix: Verify EWS is enabled in your Exchange environment.
Check the credentials configured in the Exchange subclient properties.
Test EWS connectivity using the Commvault connectivity test tool.

CV-7001: Pre-scan job failure.
Fix: Verify the Commvault services are running on the client machine.
Check network connectivity to the CommServe.
Review the client event log for service startup errors.

CV-3301: MediaAgent offline or unreachable.
Fix: Check that the MediaAgent service is running.
Verify network connectivity between CommServe and MediaAgent.
Review MediaAgent logs under Reports > Log Files.

CV-5544: Index backup failed.
Fix: Check available space in the index cache directory.
Clear old index cache files if space is low.
Re-run the index backup job manually from Job Controller.

CV-2201: Authentication failure during backup.
Fix: Verify the backup account credentials are correct.
Ensure the backup service account has the required permissions.
Re-enter credentials in the subclient properties.

CV-6601: Backup job suspended due to resource limit.
Fix: Check MediaAgent stream limits under Storage > MediaAgents.
Increase the maximum concurrent streams if utilization is low.

CV-8401: VSS snapshot creation failed.
Fix: Check VSS writer status: run vssadmin list writers.
Restart the VSS service and shadow copy providers.
Ensure at least 10% free space on the volume being snapshotted.

Scheduling best practices:
Run backups during off-peak hours, typically 10PM to 6AM.
Stagger job start times across clients to avoid resource contention.
Enable client-side deduplication to reduce data transferred over the network.
Use synthetic full backups to shorten the backup window.
Set up email alerts for failed jobs under Alerts > Configure Alerts.""",

    "restore_procedures.txt": """# Commvault Restore Procedures

## File and Folder Restore
1. In Command Center, go to Protect > Restores.
2. Select the client from the list.
3. Navigate to the backup set you want to restore from.
4. Select the files or folders you need.
5. Choose In-Place Restore for the original location, or Out-of-Place for elsewhere.
6. Click Submit. Monitor progress in the Job Controller.
7. Verify restored files by checking file timestamps and sizes.

## Virtual Machine Restore
1. Go to Protect > Virtual Machines.
2. Find your VM and click on it to view restore points.
3. Select the backup timestamp you want to restore from.
4. Choose Full VM Restore or Guest File Restore.
5. For Full VM Restore: choose the destination host, datastore, and network.
6. For in-place restore, check Overwrite existing VM.

## Cleanroom Recovery for Ransomware
Cleanroom Recovery creates an isolated environment for safe ransomware recovery.
1. Go to Protect > Cleanroom Recovery.
2. Click Create Cleanroom.
3. Select the workloads you want to recover.
4. Choose the recovery point before the ransomware incident.
5. The cleanroom spins up in an isolated network segment automatically.
6. Run malware scans inside the cleanroom before promoting to production.
7. Verify data integrity and application functionality.
8. Promote clean workloads back to production when verified.
Note: Cleanroom environments auto-expire after 72 hours by default.

## SQL Server Database Restore
1. Go to Protect > Databases.
2. Select the SQL Server instance.
3. Choose the database and the backup to restore from.
4. Select restore type: in-place, out-of-place, or table-level.
5. For point-in-time recovery: enable Restore to specific time and enter timestamp.

## Exchange Mailbox Restore
1. Go to Protect > Applications > Exchange.
2. Select the mailbox or public folder to restore.
3. Choose granular restore to recover individual emails or folders.
4. Select destination: original mailbox or alternate mailbox.

## Bare Metal Recovery
1. Boot the target machine from Commvault recovery media (ISO or USB).
2. Connect to the CommServe from the recovery wizard.
3. Select the system backup to restore from.
4. Map the original disk layout to the new hardware if different.
5. Start the restore — system will be fully rebuilt including OS and applications.""",

    "licensing.txt": """# Commvault License Management

## Checking License Status
1. In Command Center, go to Administration > License Details.
2. The License Overview shows: licensed capacity, used capacity, expiry date.
3. Color indicators: Green = valid, Yellow = expiring within 30 days, Red = expired.
4. Download the License Summary report for detailed usage by workload type.

## What Happens When a License Expires
A 14-day grace period begins automatically upon expiry.
During grace period: existing backup jobs continue to run.
During grace period: you cannot add new clients or enable new features.
After grace period ends: backup jobs stop running.
Data is NOT deleted — existing backup data remains intact.
Renewing during the grace period restores full functionality immediately.

## Activating a New License
1. Go to Administration > License > Add License.
2. Enter the activation code from your purchase confirmation email.
3. For Commvault Cloud: log in at cloud.commvault.com > Account > Licensing.
4. For a license file: use Import License and browse to the .lic file.
5. Verify the new capacity appears correctly in License Details.

## License Types
Commvault Cloud: subscription-based, managed from cloud.commvault.com.
Software perpetual: one-time purchase with annual maintenance contract.
Commvault Go: entry-level subscription for smaller environments.
Universal licensing: flexible licensing applicable across any workload.

## Reducing License Consumption
Enable deduplication on all storage policies.
Archive older data to low-cost cloud storage using HSM policies.
Remove retired clients and expired data to free up licensed capacity.""",

    "access_troubleshooting.txt": """# Commvault Access and Login Troubleshooting

## Cannot Log In to Command Center

Password forgotten:
Click Forgot Password on the Command Center login page.
The reset email comes from noreply@commvault.com — check your spam folder.
Reset link expires after 24 hours.

Account locked out:
Accounts lock after 5 consecutive failed login attempts.
Wait 15 minutes for automatic unlock.
Admin unlock: Security > Users > select user > Unlock Account.

MFA Two-Factor Authentication issues:
Check that your device clock is synchronized to UTC.
Have an admin reset MFA at Security > Users > Reset Two-Factor.
Use backup codes if you saved them during MFA enrollment.

SSO Single Sign-On problems:
Test direct access at https://your-commserve/commandcenter to bypass SSO.
If direct access works, the problem is in your identity provider configuration.
Check SAML assertion attributes — email and username must match exactly.

## Role and Permission Issues
Check user role at Security > Users > select user > Roles tab.
View role: read-only access to dashboards and reports.
Operator role: can run backups and restores, cannot change configuration.
Tenant Admin role: full administrative access within a tenant.

## API Access Issues
REST API authentication uses tokens or username/password.
Get a token: POST to /webconsole/api/Login with credentials.
Tokens expire after 30 minutes of inactivity.

## Command Center vs CommCell Console
Command Center: modern web UI at /commandcenter — recommended.
CommCell Console: legacy desktop app — being phased out.
Both connect to the same CommServe — data and configuration are shared.""",

    "performance_tuning.txt": """# Commvault Backup Performance Troubleshooting

## Diagnosing Slow Backups
Step 1: Open Job Details for the slow backup job.
Look at the Transfer Rate graph — identify when the slowdown occurs.
Flat sections mean the job is waiting: network, VSS, or index operations.

Step 2: Run the Health Report.
Go to Reports > Health Report > Generate.
It automatically flags performance issues and makes recommendations.

## Common Causes and Fixes

Antivirus scanning backup data:
Exclude Commvault installation directory from AV real-time scanning.
Exclude the index cache directory.
Exclude active backup stream paths and dedupe database paths.
This single fix often improves backup speeds by 30-50%.

Network bottleneck:
Run a bandwidth test between client and MediaAgent during backup hours.
Enable client-side deduplication to reduce data volume transferred.
Consider LAN-free backup for VMware environments.

Too many concurrent jobs:
Go to Storage > MediaAgents > Properties > Streams.
Default max streams per drive: 10 — reduce if storage is struggling.
Use job scheduling to stagger backup start times by 15-30 minutes.

Insufficient MediaAgent RAM:
Minimum for small environments: 16 GB.
For enterprise with 50+ concurrent streams: 64 GB or more.
Dedupe database operations are very RAM-intensive.

VSS snapshot taking too long:
Check VSS writer status: run vssadmin list writers.
Writers in Failed or Waiting state indicate VSS problems.
Ensure at least 10% free space on volumes being snapshotted.

## Performance Optimization Checklist
Enable software compression on storage policies for WAN backups.
Enable client-side deduplication to reduce network load.
Use block-level incremental backups for large file servers.
Schedule full backups on weekends, incrementals on weekdays.
Enable parallel streams for large jobs in subclient properties.""",

    "commvault_cloud_saas.txt": """# Commvault Cloud (SaaS) Guide

## Getting Started with Commvault Cloud
Commvault Cloud (formerly Metallic) is the SaaS version of Commvault.
Log in at cloud.commvault.com with your Commvault account.
No CommServe to manage — Commvault hosts and manages the infrastructure.

## Supported Workloads
Microsoft 365: Exchange Online, SharePoint, OneDrive, Teams.
Azure: VMs, SQL databases, Blob storage, Azure Files.
AWS: EC2 instances, RDS databases, S3 buckets.
Google Workspace: Gmail, Drive, Meet recordings.
Endpoints: Windows and Mac laptops via the Endpoint backup app.

## Setting Up Microsoft 365 Backup
1. Log in to cloud.commvault.com.
2. Go to Solutions > Microsoft 365 > Add App.
3. Authenticate with a Global Admin account to grant permissions.
4. Choose which services to protect: Exchange, SharePoint, OneDrive, Teams.
5. Configure retention: default is 1 year, extendable to indefinite.
6. First backup runs automatically within 24 hours of setup.

## Air Gap Protect for Ransomware
Air Gap Protect creates an immutable copy of backup data in Commvault's secure cloud.
Once written, data cannot be modified or deleted even by admins.
Retention lock prevents changes for the specified period (1-7 years).

## Hybrid Deployment
Run Commvault software on-premises alongside Commvault Cloud.
Use the same Command Center to manage both environments.
Tier old backup data from on-premises to Commvault Cloud for long-term retention.""",

    "command_center_guide.txt": """# Commvault Command Center Administration Guide

## Navigating Command Center
Command Center is the primary web-based management interface.
Access at: https://your-commserve-hostname/commandcenter
Dashboard: shows active jobs, storage utilization, recent alerts, and SLA status.

## Managing Clients
Add a client: Protect > Add Server > choose workload type.
Push install: enter hostname and credentials — Commvault installs the agent remotely.
Retire a client: right-click > Retire — stops backups and marks client as retired.

## Backup Plans
Plans define: backup schedule, retention, storage destination, and copy policies.
Create a plan: Manage > Plans > Add Plan.
Assign a plan to multiple clients simultaneously using bulk selection.

## Job Monitoring
View all active jobs: Home > Jobs or Job Controller in top menu.
Filter jobs: by status, client, subclient, or time range.
Kill a stuck job: right-click job > Kill Job.
Resume a suspended job: right-click > Resume.

## Alerts and Notifications
Configure alerts: Manage > Alerts > Add Alert.
Alert types: job failure, storage threshold, license expiry, client offline.
Notification methods: email, SNMP trap, webhook.

## Reports
SLA report: shows which clients met backup SLA.
Job Success Report: success/failure rates over time.
Capacity Report: data protected vs. storage consumed.
Schedule reports to email automatically daily, weekly, or monthly.""",

    "disaster_recovery.txt": """# Commvault Disaster Recovery Guide

## CommCell Disaster Recovery Planning
CommServe DR protects: database, configuration, job history, index cache.
DR backup contains: CommServe database, encryption keys, certificate files.

## CommServe DR Setup
1. Go to Control Panel > CommCell DR Backup.
2. Configure DR backup to run after every configuration change.
3. Store DR backup on a separate MediaAgent from the primary CommServe.
4. Copy DR backup files to an off-site location or cloud storage.
5. Test DR restore quarterly.

## Recovering from CommServe Failure
1. Install Commvault software on the new CommServe hardware.
2. Run the CommServe DR Restore wizard.
3. Point to the DR backup files from your last successful DR backup.
4. The CommServe database and configuration are restored.
5. Update DNS or IP settings if the hostname changed.
6. Verify MediaAgents reconnect after restore.
7. Run a test backup and restore to validate recovery.

## Multi-Site DR Architecture
Primary site: CommServe + MediaAgents + backup storage.
DR site: standby CommServe (passive) + MediaAgents + replicated backup storage.
RTO target: 2-4 hours for full CommCell recovery with proper preparation.

## Testing DR Procedures
Document and test DR procedures at least annually.
Use Cleanroom Recovery to test application recovery without impacting production.
Validate: all clients check in, all backup jobs run, test restore succeeds.""",

    "network_configuration.txt": """# Commvault Network Configuration Guide

## Required Ports and Firewall Rules
CommServe to client communication: TCP port 8400 (bidirectional).
Client to CommServe registration: TCP port 8400 outbound from client.
Command Center web access: TCP port 80 (HTTP) and 443 (HTTPS).
CommCell Console (legacy): TCP port 8401.
Cloud backups to Commvault Cloud: HTTPS outbound TCP port 443.

## Network Topology Best Practices
Keep CommServe and primary MediaAgent on the same LAN for low latency.
MediaAgents should be physically close to the storage they manage.
Place a MediaAgent in each remote site to avoid WAN backup traffic.
Use network throttling policies to limit backup bandwidth on slow WAN links.

## Firewall Traversal for Remote Clients
For clients behind NAT or strict firewalls, use Commvault's proxy configuration.
Install a Network Gateway on a DMZ machine with access to both networks.
Clients connect to the gateway, which relays traffic to CommServe.

## DNS Requirements
CommServe hostname must resolve correctly from all clients and MediaAgents.
All clients must be resolvable by hostname from CommServe.
Check DNS resolution: run nslookup commserve-hostname from each client.

## SSL and Encryption
Enable SSL for Command Center: Settings > Security > Enable HTTPS.
Data in transit encryption: enable in storage policy properties > Encryption.
Data at rest encryption: configure in the storage library properties.
Key management: Commvault Key Management Server or external KMS.""",

    "vm_protection.txt": """# Virtual Machine Protection with Commvault

## VMware vSphere Backup
Commvault uses VMware CBT (Changed Block Tracking) for incremental backups.
No agent required inside the guest VM — backup runs at the hypervisor level.

Setup:
1. Add vCenter as a virtualization client: Protect > Virtualization > Add Client.
2. Enter vCenter credentials with backup privileges.
3. Discover VMs — they appear automatically under the vCenter client.
4. Create a VM group (subclient) and assign a backup plan.
5. First backup is a full; subsequent backups use CBT for increments.

Best practices:
Enable CBT on all VMs before the first backup.
Keep VMware Tools updated — required for application-consistent snapshots.
Schedule VM backups to avoid snapshot accumulation during business hours.

## Application-Consistent vs Crash-Consistent
Application-consistent: uses VSS or VMware quiescing to flush in-memory data.
Recommended for: SQL Server, Exchange, Oracle, Active Directory.
Crash-consistent: snapshot taken without quiescing.
Acceptable for: stateless workloads.

## VM Replication for DR
Commvault Live Sync replicates VMs to a DR site continuously.
RPO as low as 15 minutes for critical VMs.
Setup: Protect > Replication > Configure Live Sync.
Failover: Protect > Replication > select VM > Failover.
Test failover: runs in an isolated network — no impact to production.

## Granular VM Recovery Options
Full VM restore: restores the entire VM to original or alternate location.
Guest file restore: mount the backup and browse files without restoring the VM.
Instant VM recovery: mount the backup as a live VM in seconds.""",
}


# ── RAG pipeline ──────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def build_kb(_groq_key: str):
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain.schema import Document

    index_dir = Path("data/kb_index")
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    if index_dir.exists() and (index_dir / "index.faiss").exists():
        return FAISS.load_local(str(index_dir), embeddings, allow_dangerous_deserialization=True)

    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=80)
    all_chunks = []
    for filename, content in KB_DOCS.items():
        docs = [Document(page_content=content, metadata={"source_file": filename, "category": filename.replace(".txt", "")})]
        chunks = splitter.split_documents(docs)
        for i, c in enumerate(chunks):
            c.metadata["chunk_index"] = i
        all_chunks.extend(chunks)

    store = FAISS.from_documents(all_chunks, embeddings)
    index_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(index_dir))
    return store


def _compute_confidence(results_with_scores: list) -> float:
    if not results_with_scores:
        return 0.0
    avg = sum(s for _, s in results_with_scores) / len(results_with_scores)
    return round(max(0.0, min(1.0, 1.0 - avg / 2.0)), 3)


GREETING_RESPONSE = (
    "Hello! I'm AEGIS, your AI support assistant for Commvault backup and recovery.\n\n"
    "I can help with:\n"
    "- **Backup failures** and error codes (CV-XXXXX)\n"
    "- **Restore procedures** — files, VMs, databases, bare metal\n"
    "- **Licensing** — activation, renewals, grace period\n"
    "- **Performance** troubleshooting and optimization\n"
    "- **Access and login** issues\n"
    "- **Commvault Cloud** (SaaS) and on-premises\n\n"
    "What can I help you with today?"
)

SYSTEM_PROMPT = (
    "You are AEGIS, an expert AI support assistant for Commvault — a data protection and cyber resilience platform. "
    "Your job is to help support agents and customers troubleshoot issues quickly and accurately. "
    "Rules: answer ONLY from the context provided below, be specific and actionable, "
    "use numbered steps for procedures, cite the source document when answering. "
    "If context doesn't cover the question fully, say so clearly and offer to escalate.\n\n"
    "Context:\n{context}"
)


def rag_query(question: str, store, groq_key: str) -> dict:
    import time as _time
    from groq import Groq

    t0 = _time.time()

    q_lower = question.lower().strip()
    if q_lower in GREETINGS or (len(q_lower.split()) <= 3 and any(g in q_lower for g in GREETINGS)):
        return {
            "content": GREETING_RESPONSE, "action": "RESPOND",
            "confidence": 1.0, "sources": [],
            "latency_ms": round((_time.time() - t0) * 1000),
        }

    results = store.similarity_search_with_score(question, k=5)
    confidence = _compute_confidence(results)
    sources = [{"source": d.metadata.get("source_file", "?"), "category": d.metadata.get("category", "")} for d, _ in results]

    if confidence < 0.35:
        _save_kb_gap(question, classify(question)[0], confidence)
        return {
            "content": (
                "I don't have confident information about that in my knowledge base. "
                "I'll escalate this to a support specialist who can help directly."
            ),
            "action": "ESCALATE", "confidence": confidence,
            "sources": sources, "latency_ms": round((_time.time() - t0) * 1000),
        }

    context = "\n\n".join(
        f"[Source: {d.metadata.get('source_file','?')}]\n{d.page_content}"
        for d, _ in results
    )

    client = Groq(api_key=groq_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
        max_tokens=700,
        temperature=0.1,
    )

    return {
        "content": response.choices[0].message.content,
        "action": "RESPOND", "confidence": confidence,
        "sources": sources, "latency_ms": round((_time.time() - t0) * 1000),
    }


def stream_rag_query(question: str, store, groq_key: str):
    from groq import Groq

    q_lower = question.lower().strip()
    if q_lower in GREETINGS or (len(q_lower.split()) <= 3 and any(g in q_lower for g in GREETINGS)):
        def greet():
            yield GREETING_RESPONSE
        return greet(), 1.0, [], "RESPOND"

    results = store.similarity_search_with_score(question, k=5)
    confidence = _compute_confidence(results)
    sources = [{"source": d.metadata.get("source_file", "?"), "category": d.metadata.get("category", "")} for d, _ in results]

    if confidence < 0.35:
        _save_kb_gap(question, classify(question)[0], confidence)
        def esc():
            yield (
                "I don't have confident information about that in my knowledge base. "
                "I'll escalate this to a support specialist who can help directly."
            )
        return esc(), confidence, sources, "ESCALATE"

    context = "\n\n".join(
        f"[Source: {d.metadata.get('source_file','?')}]\n{d.page_content}"
        for d, _ in results
    )

    client = Groq(api_key=groq_key)
    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
        max_tokens=700, temperature=0.1, stream=True,
    )

    def tokens():
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return tokens(), confidence, sources, "RESPOND"


def get_followups(question: str, answer: str, groq_key: str) -> list:
    from groq import Groq
    try:
        client = Groq(api_key=groq_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"Based on this Commvault support conversation:\nQ: {question}\nA: {answer[:300]}\n\n"
                "Generate exactly 3 short follow-up questions. Each on its own line. Max 10 words each. No bullets."
            )}],
            max_tokens=90, temperature=0.7,
        )
        lines = resp.choices[0].message.content.strip().split("\n")
        return [l.strip().lstrip("•-123456789. ") for l in lines if l.strip()][:3]
    except Exception:
        return []


def auto_generate_kb_article(resolved_ticket: dict, groq_key: str) -> str:
    from groq import Groq
    try:
        client = Groq(api_key=groq_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"A Commvault support ticket was resolved. Write a concise KB article from it.\n\n"
                f"Issue: {resolved_ticket.get('subject', '')}\n"
                f"Details: {resolved_ticket.get('body', '')[:300]}\n"
                f"Category: {resolved_ticket.get('intent', '')}\n\n"
                "Format: ## Problem\n[description]\n## Cause\n[cause]\n## Solution\n1. [step]\n2. [step]"
            )}],
            max_tokens=400, temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception:
        return ""


# ── Database helpers ──────────────────────────────────────────────────────────

def save_ticket(subject, body, intent, priority, team, confidence, source, tier, esc=None, assigned_to=None):
    c = db()
    r = c.execute(
        "INSERT INTO tickets(subject,body,intent,priority,team,confidence,source,tier,escalation_reason,assigned_to)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (subject[:500], body[:2000], intent, priority, team, confidence, source, tier, esc, assigned_to),
    )
    c.commit(); tid = r.lastrowid; c.close()
    return tid


def update_ticket(ticket_id: int, **kwargs):
    allowed = {"status", "priority", "team", "assigned_to", "csat", "resolution_note", "resolved_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    c = db()
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [ticket_id]
    c.execute(f"UPDATE tickets SET {sets}, updated_at=datetime('now') WHERE id=?", vals)
    c.commit(); c.close()


def load_tickets(status=None, intent=None, priority=None, search=None, limit=100, offset=0):
    c = db()
    q = "SELECT * FROM tickets WHERE 1=1"
    p = []
    if status and status != "all":
        q += " AND status=?"; p.append(status)
    if intent and intent != "all":
        q += " AND intent=?"; p.append(intent)
    if priority and priority != "all":
        q += " AND priority=?"; p.append(priority)
    if search:
        q += " AND (subject LIKE ? OR body LIKE ?)"
        p.extend([f"%{search}%", f"%{search}%"])
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    p.extend([limit, offset])
    rows = c.execute(q, p).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_ticket_count(**filters):
    c = db()
    q = "SELECT COUNT(*) FROM tickets WHERE 1=1"
    p = []
    for k, v in filters.items():
        if v and v != "all":
            q += f" AND {k}=?"; p.append(v)
    count = c.execute(q, p).fetchone()[0]
    c.close()
    return count


def save_event(sid, intent, confidence, action, latency):
    c = db()
    c.execute("INSERT INTO events(session_id,intent,confidence,action,latency_ms) VALUES(?,?,?,?,?)",
              (sid, intent, confidence, action, latency))
    c.commit(); c.close()


def save_email_log(sender, subject, intent, action, template, sentiment="neutral"):
    c = db()
    c.execute("INSERT INTO email_log(sender,subject,intent,action,template,sentiment) VALUES(?,?,?,?,?,?)",
              (sender, subject[:300], intent, action, template, sentiment))
    c.commit(); c.close()


def _save_kb_gap(query, intent, confidence):
    c = db()
    c.execute("INSERT INTO kb_gaps(query,intent,confidence) VALUES(?,?,?)", (query, intent, confidence))
    c.commit(); c.close()


def save_csat(ticket_id, session_id, rating, comment=""):
    c = db()
    c.execute("INSERT INTO csat_ratings(ticket_id,session_id,rating,comment) VALUES(?,?,?,?)",
              (ticket_id, session_id, rating, comment))
    c.execute("UPDATE tickets SET csat=? WHERE id=?", [rating, ticket_id])
    c.commit(); c.close()


def get_full_analytics(days=7):
    c = db()
    cut = (datetime.now() - timedelta(days=days)).isoformat()
    prev_cut = (datetime.now() - timedelta(days=days * 2)).isoformat()

    total     = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=?", [cut]).fetchone()[0]
    prev      = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=? AND created_at<?", [prev_cut, cut]).fetchone()[0]
    bot       = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=? AND source='chatbot'", [cut]).fetchone()[0]
    esc       = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=? AND escalation_reason IS NOT NULL", [cut]).fetchone()[0]
    resolved  = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=? AND status IN ('resolved','closed')", [cut]).fetchone()[0]
    avg_csat  = c.execute("SELECT AVG(rating) FROM csat_ratings WHERE created_at>=?", [cut]).fetchone()[0] or 0
    avg_conf  = c.execute("SELECT AVG(confidence) FROM events WHERE created_at>=? AND confidence IS NOT NULL", [cut]).fetchone()[0] or 0
    p1_count  = c.execute("SELECT COUNT(*) FROM tickets WHERE created_at>=? AND priority='P1'", [cut]).fetchone()[0]
    open_p1   = c.execute("SELECT COUNT(*) FROM tickets WHERE priority='P1' AND status='open'", []).fetchone()[0]

    intents   = c.execute("SELECT intent,COUNT(*) FROM tickets WHERE created_at>=? AND intent IS NOT NULL GROUP BY intent ORDER BY COUNT(*) DESC", [cut]).fetchall()
    priorities= c.execute("SELECT priority,COUNT(*) FROM tickets WHERE created_at>=? GROUP BY priority ORDER BY priority", [cut]).fetchall()
    statuses  = c.execute("SELECT status,COUNT(*) FROM tickets WHERE created_at>=? GROUP BY status", [cut]).fetchall()
    daily     = c.execute("SELECT DATE(created_at),COUNT(*),SUM(CASE WHEN source='chatbot' THEN 1 ELSE 0 END),SUM(CASE WHEN escalation_reason IS NOT NULL THEN 1 ELSE 0 END) FROM tickets WHERE created_at>=? GROUP BY DATE(created_at) ORDER BY 1", [cut]).fetchall()
    kb_gaps   = c.execute("SELECT intent,COUNT(*) as freq,AVG(confidence) as avg_conf FROM kb_gaps WHERE created_at>=? GROUP BY intent ORDER BY freq DESC LIMIT 8", [cut]).fetchall()
    csat_dist = c.execute("SELECT rating,COUNT(*) FROM csat_ratings WHERE created_at>=? GROUP BY rating ORDER BY rating", [cut]).fetchall()
    email_actions = c.execute("SELECT action,COUNT(*) FROM email_log WHERE created_at>=? GROUP BY action", [cut]).fetchall()

    c.close()
    return {
        "total": total, "prev_total": prev,
        "bot_handled": bot,
        "automation_rate": round(bot / max(total, 1) * 100, 1),
        "escalation_rate": round(esc / max(total, 1) * 100, 1),
        "resolution_rate": round(resolved / max(total, 1) * 100, 1),
        "avg_csat": round(avg_csat, 2), "avg_confidence": round(avg_conf, 3),
        "p1_count": p1_count, "open_p1": open_p1,
        "intents": [{"intent": r[0], "count": r[1]} for r in intents],
        "priorities": dict(priorities), "statuses": dict(statuses),
        "daily": [{"date": r[0], "total": r[1], "bot": r[2], "escalated": r[3]} for r in daily],
        "kb_gaps": [{"intent": r[0], "frequency": r[1], "avg_confidence": round(r[2], 3)} for r in kb_gaps],
        "csat_distribution": dict(csat_dist),
        "email_actions": dict(email_actions),
    }


def compute_sla_status(ticket: dict) -> tuple[str, str]:
    hours_limit = SLA_HOURS.get(ticket.get("priority", "P3"), 72)
    created = datetime.fromisoformat(ticket["created_at"]) if ticket.get("created_at") else datetime.now()
    elapsed = (datetime.now() - created).total_seconds() / 3600

    if ticket.get("status") in ("resolved", "closed"):
        return "resolved", "✅ Resolved"

    pct = elapsed / hours_limit
    if pct >= 1.0:
        return "breach", f"🔴 BREACHED ({elapsed:.0f}h / {hours_limit}h)"
    elif pct >= 0.8:
        remaining = hours_limit - elapsed
        return "warning", f"🟡 {remaining:.1f}h left"
    else:
        remaining = hours_limit - elapsed
        return "ok", f"🟢 {remaining:.1f}h left"


def tickets_to_csv(tickets: list) -> str:
    if not tickets:
        return ""
    buf = io.StringIO()
    fields = ["id", "subject", "intent", "priority", "team", "status", "source",
              "tier", "confidence", "escalation_reason", "csat", "created_at", "resolved_at"]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(tickets)
    return buf.getvalue()


# ── Initialise ────────────────────────────────────────────────────────────────

init_db()

defaults = {
    "session_id": f"s-{int(time.time())}",
    "messages": [], "followups": [],
    "show_create": False, "csat_pending": None,
    "kb_search": "", "ticket_search": "",
    "settings": {
        "confidence_threshold": 0.35,
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 700,
        "top_k": 5,
        "chunk_size": 700,
    }
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🛡️ AEGIS")
    st.caption("AI Support Automation Engine\nCommvault · Enterprise Grade")
    st.divider()

    page = st.radio("Navigation",
        ["🏠 Dashboard", "💬 Chatbot", "🎫 Ticket Inbox",
         "📧 Email Hub", "📊 Analytics", "📚 Knowledge Base", "⚙️ Settings"],
        label_visibility="collapsed")

    st.divider()
    groq_key = get_groq_key()

    if not groq_key:
        groq_key = st.text_input(
            "Groq API Key", type="password", placeholder="gsk-...",
            help="Free key at console.groq.com — no credit card")
        if groq_key:
            st.session_state["groq_key"] = groq_key

    if groq_key:
        with st.spinner("Loading KB..."):
            try:
                store = build_kb(groq_key)
                doc_count = len(KB_DOCS)
                st.success(f"✅ Connected\nModel: Llama 3.3 70B\nKB: {doc_count} documents")
            except Exception as e:
                st.error(f"KB error: {str(e)[:80]}")
                store = None
    else:
        store = None
        st.warning("Add your Groq API key above.\nFree key: console.groq.com")

    st.divider()

    open_p1 = get_ticket_count(priority="P1", status="open")
    if open_p1 > 0:
        st.markdown(f'<div class="alert-banner">⚡ <b>{open_p1} open P1 ticket{"s" if open_p1 > 1 else ""}</b> need attention</div>', unsafe_allow_html=True)

    st.caption("Built by **Harsha Venkateshwara**\nMS CS&E · University at Buffalo")


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

if page == "🏠 Dashboard":
    st.title("🏠 AEGIS Dashboard")
    st.caption("Real-time support operations overview")

    col_period, col_refresh = st.columns([3, 1])
    with col_period:
        period = st.selectbox("Period", [7, 14, 30], format_func=lambda x: f"Last {x} days", label_visibility="collapsed")
    with col_refresh:
        if st.button("↻ Refresh", use_container_width=True):
            st.rerun()

    data = get_full_analytics(period)

    delta_total = data["total"] - data["prev_total"]

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Tickets", data["total"], delta=f"{delta_total:+d} vs prev period")
    k2.metric("Automation Rate", f"{data['automation_rate']}%", help="% resolved by chatbot without human")
    k3.metric("Escalation Rate", f"{data['escalation_rate']}%")
    k4.metric("Resolution Rate", f"{data['resolution_rate']}%")
    k5.metric("Avg CSAT", f"{data['avg_csat']:.1f}/5" if data["avg_csat"] else "—")
    k6.metric("KB Confidence", f"{data['avg_confidence']:.0%}")

    if data["open_p1"] > 0:
        st.markdown(f'<div class="alert-banner">⚡ <b>{data["open_p1"]} P1 ticket{"s" if data["open_p1"] > 1 else ""} are open and may be breaching SLA</b></div>', unsafe_allow_html=True)

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        import plotly.graph_objects as go

        st.subheader("Ticket volume trend")
        daily = data.get("daily", [])
        if daily:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=[d["date"] for d in daily], y=[d["total"] for d in daily], name="Total", marker_color="#ccd9e6"))
            fig.add_trace(go.Bar(x=[d["date"] for d in daily], y=[d["bot"] for d in daily], name="Bot resolved", marker_color="#1F4E79"))
            fig.add_trace(go.Scatter(x=[d["date"] for d in daily], y=[d["escalated"] for d in daily], name="Escalated", mode="lines+markers", line=dict(color="#dc3545", width=2)))
            fig.update_layout(barmode="overlay", height=260, margin=dict(l=0,r=0,t=0,b=0), showlegend=True, legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No ticket data yet.")

    with col_right:
        st.subheader("Recent P1 and P2 tickets")
        urgent = load_tickets(priority="P1", limit=5) + load_tickets(priority="P2", limit=3)
        urgent.sort(key=lambda x: x["created_at"], reverse=True)
        if urgent:
            for t in urgent[:6]:
                sla_status, sla_label = compute_sla_status(t)
                icon = "🔴" if t["priority"] == "P1" else "🟠"
                st.markdown(f"{icon} **#{t['id']}** {t['subject'][:50]}  \n"
                            f"<small>{t.get('intent','—')} · {sla_label}</small>", unsafe_allow_html=True)
        else:
            st.success("No urgent open tickets.")

    st.divider()

    col3, col4, col5 = st.columns(3)

    with col3:
        import plotly.express as px
        st.subheader("By intent")
        intents = data.get("intents", [])
        if intents:
            fig = px.bar(x=[i["count"] for i in intents], y=[i["intent"] for i in intents],
                         orientation="h", color=[i["count"] for i in intents], color_continuous_scale="Blues")
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    with col4:
        st.subheader("By status")
        statuses = data.get("statuses", {})
        if statuses:
            fig = px.pie(values=list(statuses.values()), names=list(statuses.keys()),
                         color_discrete_sequence=["#1F4E79","#2E75B6","#9DC3E6","#BDD7EE"], hole=0.45)
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=0,b=0), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)

    with col5:
        st.subheader("KB coverage gaps")
        gaps = data.get("kb_gaps", [])
        if gaps:
            for g in gaps[:5]:
                conf = g["avg_confidence"]
                bar = "🔴" if conf < 0.30 else "🟡" if conf < 0.50 else "🟢"
                st.markdown(f"{bar} **{g['intent']}** — {g['frequency']}x · conf {conf:.0%}")
        else:
            st.success("No KB gaps detected.")

    st.divider()

    st.subheader("SLA status — all open tickets")
    open_tickets = load_tickets(status="open", limit=20)
    if open_tickets:
        sla_data = []
        for t in open_tickets:
            _, sla_label = compute_sla_status(t)
            sla_data.append({
                "ID": t["id"], "Subject": t["subject"][:50],
                "Priority": t["priority"], "Intent": t.get("intent","—"),
                "Team": t.get("team","—"), "SLA": sla_label,
                "Created": t["created_at"][:16],
            })
        st.dataframe(sla_data, use_container_width=True, hide_index=True)
    else:
        st.success("No open tickets — queue is clear.")


# ══════════════════════════════════════════════════════════════════════════════
# CHATBOT
# ══════════════════════════════════════════════════════════════════════════════

elif page == "💬 Chatbot":
    st.title("💬 AI Support Chatbot")
    st.caption("Streaming RAG · FAISS · Llama 3.3 70B on Groq · 10 Commvault KB documents · Zero cost")

    col1, col2 = st.columns([3, 1])

    with col1:
        if not st.session_state.messages:
            st.info("👋 Ask anything about Commvault backup errors, restore procedures, licensing, performance, or access issues.")

        for msg in st.session_state.messages:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(msg.get("content", ""))
            else:
                with st.chat_message("assistant", avatar="🛡️"):
                    content = msg.get("content", "")
                    action  = msg.get("action", "RESPOND")
                    if action == "ESCALATE":
                        st.warning(f"⚡ **Escalated to support team**\n\n{content}")
                    else:
                        st.markdown(content)

                    conf = msg.get("confidence", 0)
                    lat  = msg.get("latency_ms", 0)
                    srcs = " · ".join(s["source"] for s in msg.get("sources", [])[:3])
                    st.caption(f"Confidence: {conf:.0%} · {lat}ms · Groq Llama 3.3 · {srcs}")

                    tid = msg.get("ticket_id")
                    if msg.get("show_csat") and tid:
                        st.markdown("**Rate this response:**")
                        rating_cols = st.columns(5)
                        for star in range(1, 6):
                            with rating_cols[star - 1]:
                                if st.button("★" * star, key=f"csat_{tid}_{star}_{msg.get('msg_idx',0)}"):
                                    save_csat(tid, st.session_state.session_id, star)
                                    msg["show_csat"] = False
                                    st.rerun()

        if st.session_state.followups:
            st.markdown("**Suggested follow-ups:**")
            fu_cols = st.columns(3)
            for i, suggestion in enumerate(st.session_state.followups):
                with fu_cols[i % 3]:
                    if st.button(suggestion, key=f"fu_{i}_{suggestion[:8]}", use_container_width=True):
                        st.session_state.followups = []
                        st.session_state.messages.append({"role": "user", "content": suggestion})
                        intent, escalate = classify(suggestion)
                        if escalate or store is None or not groq_key:
                            st.session_state.messages.append({
                                "role": "assistant", "content": "Connecting you with a specialist.",
                                "action": "ESCALATE", "confidence": 1.0, "sources": [], "latency_ms": 0,
                            })
                        else:
                            gen, conf, srcs, action = stream_rag_query(suggestion, store, groq_key)
                            with st.chat_message("assistant", avatar="🛡️"):
                                full = st.write_stream(gen)
                                st.caption(f"Confidence: {conf:.0%} · Groq Llama 3.3")
                            st.session_state.messages.append({
                                "role": "assistant", "content": full,
                                "action": action, "confidence": conf, "sources": srcs, "latency_ms": 0,
                            })
                            if action == "RESPOND":
                                st.session_state.followups = get_followups(suggestion, full, groq_key)
                        save_event(st.session_state.session_id, intent, conf if not escalate else 1.0, "ESCALATE" if escalate else action, 0)
                        st.rerun()

        user_input = st.chat_input("Ask about Commvault backup, restore, licensing, or troubleshooting...")

        if user_input:
            st.session_state.followups = []
            st.session_state.messages.append({"role": "user", "content": user_input})
            intent, escalate = classify(user_input)

            if not groq_key:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Add your Groq API key in the sidebar to enable the chatbot.",
                    "action": "ERROR", "confidence": 0, "sources": [], "latency_ms": 0,
                })
            elif escalate or store is None:
                tier = st.session_state.get("tier", "standard")
                priority = PRIORITY_MAP.get(intent, "P2")
                team = TEAM_MAP.get(intent, "senior_support")
                if tier == "enterprise":
                    priority = "P1"
                tid = save_ticket(user_input[:100], user_input, intent, priority, team, 1.0, "chatbot", tier, "chat_escalation")
                reply = f"I'll connect you with a support specialist right away.\n\n📋 **Ticket #{tid}** created · Priority: {priority} · Team: {team}"
                st.session_state.messages.append({
                    "role": "assistant", "content": reply, "action": "ESCALATE",
                    "confidence": 1.0, "sources": [], "latency_ms": 0, "ticket_id": tid, "show_csat": True,
                    "msg_idx": len(st.session_state.messages),
                })
                save_event(st.session_state.session_id, intent, 1.0, "ESCALATE", 0)
            else:
                import time as _t
                t0 = _t.time()
                gen, conf, srcs, action = stream_rag_query(user_input, store, groq_key)
                with st.chat_message("assistant", avatar="🛡️"):
                    full_response = st.write_stream(gen)
                    lat = round((_t.time() - t0) * 1000)
                    src_text = " · ".join(s["source"] for s in srcs[:3])
                    st.caption(f"Confidence: {conf:.0%} · {lat}ms · Groq Llama 3.3 · {src_text}")

                tid = None
                if action == "ESCALATE":
                    tier = st.session_state.get("tier", "standard")
                    tid = save_ticket(user_input[:100], user_input, intent, PRIORITY_MAP.get(intent,"P2"),
                                      TEAM_MAP.get(intent,"senior_support"), conf, "chatbot", tier, "low_confidence")
                    full_response += f"\n\n📋 **Ticket #{tid}** created."

                st.session_state.messages.append({
                    "role": "assistant", "content": full_response,
                    "action": action, "confidence": conf, "sources": srcs, "latency_ms": lat,
                    "ticket_id": tid, "show_csat": action == "RESPOND",
                    "msg_idx": len(st.session_state.messages),
                })

                if action == "RESPOND" and groq_key:
                    st.session_state.followups = get_followups(user_input, full_response, groq_key)

                save_event(st.session_state.session_id, intent, conf, action, lat)

            st.rerun()

    with col2:
        st.subheader("Quick demos")
        demos = [
            "Backup job failed with CV-12345",
            "How do I restore a VM?",
            "What is Cleanroom Recovery?",
            "My license has expired",
            "Can't log in to Command Center",
            "Backups are running very slowly",
            "Set up Microsoft 365 backup",
            "How does Air Gap Protect work?",
            "Explain CommServe DR backup",
            "I need to speak to a human",
        ]
        for q in demos:
            if st.button(q, use_container_width=True, key=f"demo_{hashlib.md5(q.encode()).hexdigest()[:6]}"):
                st.session_state.followups = []
                st.session_state.messages.append({"role": "user", "content": q})
                intent, escalate = classify(q)
                if escalate or store is None or not groq_key:
                    result = {"content": "Connecting you with a specialist.", "action": "ESCALATE", "confidence": 1.0, "sources": [], "latency_ms": 0}
                else:
                    result = rag_query(q, store, groq_key)
                st.session_state.messages.append({"role": "assistant", **result, "msg_idx": len(st.session_state.messages)})
                if result["action"] == "RESPOND" and groq_key:
                    st.session_state.followups = get_followups(q, result.get("content",""), groq_key)
                save_event(st.session_state.session_id, intent, result["confidence"], result["action"], result["latency_ms"])
                st.rerun()

        st.divider()

        if st.button("Export conversation", use_container_width=True):
            export = "\n\n".join(
                f"{'You' if m['role']=='user' else 'AEGIS'}: {m.get('content','')}"
                for m in st.session_state.messages
            )
            st.download_button("⬇ Download .txt", export, file_name=f"aegis_chat_{datetime.now().strftime('%Y%m%d_%H%M')}.txt", use_container_width=True)

        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.followups = []
            st.session_state.session_id = f"s-{int(time.time())}"
            st.rerun()

        st.divider()
        st.selectbox("Customer tier", ["standard", "premium", "enterprise", "trial"], key="tier")
        st.caption(f"Session: {st.session_state.session_id[-8:]}")
        st.caption(f"Messages: {len(st.session_state.messages)}")


# ══════════════════════════════════════════════════════════════════════════════
# TICKET INBOX
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🎫 Ticket Inbox":
    st.title("🎫 Ticket Inbox")
    st.caption("Auto-classified · Priority-ranked · SLA-tracked")

    filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns([2, 1.5, 1.5, 1.5, 1])

    with filter_col1:
        search = st.text_input("Search", placeholder="Search tickets...", label_visibility="collapsed", key="ticket_search_input")
    with filter_col2:
        sf_status   = st.selectbox("Status",   ["all","open","in_progress","resolved","closed"], label_visibility="collapsed")
    with filter_col3:
        sf_priority = st.selectbox("Priority", ["all","P1","P2","P3","P4"], label_visibility="collapsed")
    with filter_col4:
        sf_intent   = st.selectbox("Intent",   ["all","backup_failure","restore_request","licensing","access_issue","performance","billing","general_inquiry"], label_visibility="collapsed")
    with filter_col5:
        if st.button("➕ New", use_container_width=True):
            st.session_state.show_create = True

    if st.session_state.show_create:
        with st.form("create_ticket_form"):
            st.subheader("Create Ticket")
            c1, c2 = st.columns(2)
            with c1:
                subj = st.text_input("Subject", value="Backup job failed overnight — SQL Server DB01")
                body = st.text_area("Body", value="Error CV-12345 on nightly SQL Server backup. Failed at 40% at 3AM. Production database.")
            with c2:
                tier     = st.selectbox("Customer tier", ["standard","premium","enterprise","trial"])
                assigned = st.text_input("Assign to", placeholder="agent@company.com")

            if st.form_submit_button("Submit →"):
                intent, _ = classify(f"{subj} {body}")
                priority  = PRIORITY_MAP.get(intent, "P3")
                team      = TEAM_MAP.get(intent, "general_support")
                if tier == "enterprise" and priority in ("P3","P4"):
                    priority = "P2"
                tid = save_ticket(subj, body, intent, priority, team, get_confidence_from_text(f"{subj} {body}"), "manual", tier, assigned_to=assigned or None)
                st.success(f"✅ Ticket #{tid} created → **{intent}** → {team} [{priority}]")
                st.session_state.show_create = False
                st.rerun()

    tickets = load_tickets(
        status=sf_status, intent=sf_intent, priority=sf_priority,
        search=search if search else None, limit=50
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Shown",     len(tickets))
    m2.metric("P1 open",   get_ticket_count(priority="P1", status="open"))
    m3.metric("P2 open",   get_ticket_count(priority="P2", status="open"))
    m4.metric("Escalated", sum(1 for t in tickets if t.get("escalation_reason")))
    m5.metric("Avg conf",  f"{sum(t.get('confidence',0) for t in tickets)/max(len(tickets),1):.0%}")

    if tickets:
        csv_data = tickets_to_csv(tickets)
        st.download_button("⬇ Export to CSV", csv_data, file_name=f"tickets_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

    st.divider()

    if not tickets:
        st.info("No tickets match your filters. Try adjusting the search or filters above.")
    else:
        for t in tickets:
            p = t.get("priority","P3")
            icon = {"P1":"🔴","P2":"🟠","P3":"🟡","P4":"⚪"}.get(p,"🟡")
            sla_status, sla_label = compute_sla_status(t)
            esc_flag = "⚡" if t.get("escalation_reason") else ""

            with st.expander(f"{icon} #{t['id']} · {t['subject'][:60]} {esc_flag}"):
                row1, row2, row3, row4, row5 = st.columns(5)
                row1.markdown(f"**Priority**\n\n{p}")
                row2.markdown(f"**Intent**\n\n{t.get('intent') or '—'}")
                row3.markdown(f"**Team**\n\n{t.get('team') or '—'}")
                row4.markdown(f"**Tier**\n\n{t.get('tier') or '—'}")
                conf_display = f"{t['confidence']:.0%}" if t.get('confidence') else '—'
                row5.markdown(f"**Confidence**\n\n{conf_display}")

                st.markdown(f"**SLA:** {sla_label} &nbsp; **Source:** {t.get('source','—')} &nbsp; **Created:** {t.get('created_at','')[:16]}", unsafe_allow_html=True)

                if t.get("escalation_reason"):
                    st.warning(f"⚡ Escalated: {t['escalation_reason']}")
                if t.get("csat"):
                    st.info(f"⭐ CSAT: {'★' * t['csat']}{'☆' * (5 - t['csat'])}")
                if t.get("resolution_note"):
                    st.success(f"📝 Resolution: {t['resolution_note']}")

                st.text_area("Body preview", value=t.get("body","")[:300], height=80, disabled=True, key=f"body_{t['id']}", label_visibility="collapsed")

                edit_c1, edit_c2, edit_c3, edit_c4 = st.columns(4)
                with edit_c1:
                    opts = ["open","in_progress","resolved","closed"]
                    cur  = t.get("status","open")
                    ns   = st.selectbox("Status", opts, index=opts.index(cur) if cur in opts else 0, key=f"st_{t['id']}", label_visibility="collapsed")
                with edit_c2:
                    np = st.selectbox("Priority", ["P1","P2","P3","P4"],
                                      index=["P1","P2","P3","P4"].index(p) if p in ["P1","P2","P3","P4"] else 2,
                                      key=f"pr_{t['id']}", label_visibility="collapsed")
                with edit_c3:
                    note = st.text_input("Resolution note", key=f"rn_{t['id']}", placeholder="How was this resolved?", label_visibility="collapsed")
                with edit_c4:
                    if st.button("Save", key=f"save_{t['id']}", use_container_width=True):
                        updates = {"status": ns, "priority": np}
                        if note:
                            updates["resolution_note"] = note
                        if ns in ("resolved","closed") and t.get("status") not in ("resolved","closed"):
                            updates["resolved_at"] = datetime.now().isoformat()
                        update_ticket(t["id"], **updates)
                        st.rerun()

                if groq_key and st.button(f"Generate KB article from #{t['id']}", key=f"kb_{t['id']}"):
                    with st.spinner("Generating KB article..."):
                        article = auto_generate_kb_article(t, groq_key)
                    if article:
                        st.text_area("Generated KB Article (copy to add to KB):", article, height=200, key=f"kb_art_{t['id']}")


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL HUB
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📧 Email Hub":
    st.title("📧 Email Automation Hub")
    st.caption("Classify → template match → auto-respond or escalate")

    tab1, tab2, tab3 = st.tabs(["Process Email", "Batch Simulation", "Email Log"])

    with tab1:
        col1, col2 = st.columns([3, 2])
        with col1:
            with st.form("email_form"):
                sender  = st.text_input("From", value="customer@acmecorp.com")
                subject = st.text_input("Subject", value="Commvault license expiring in 3 days — urgent")
                body    = st.text_area("Body",
                    value="Our Commvault Cloud license expires in 3 days. Account ACC-44821. "
                          "We have 150 VMs that will be unprotected. Please help us process renewal urgently.",
                    height=100)
                tier    = st.selectbox("Customer tier", ["standard","premium","enterprise","trial"])
                go      = st.form_submit_button("Process Email →", use_container_width=True)

            if go:
                intent, escalate = classify(f"{subject} {body}")
                sentiment = "neutral"
                if any(w in body.lower() for w in ["urgent","critical","asap","immediately","production down"]):
                    sentiment = "frustrated"
                elif any(w in body.lower() for w in ["thank","appreciate","great","happy"]):
                    sentiment = "positive"

                action   = "escalated" if escalate else "auto_responded"
                template = f"{intent}_ack.html" if not escalate else None
                save_email_log(sender, subject, intent, action, template, sentiment)

                if escalate:
                    st.warning(f"⚡ **Escalated** · Intent: `{intent}` · Sentiment: `{sentiment}` → Senior support")
                else:
                    st.success(f"✅ **Auto-responded** · Intent: `{intent}` · Sentiment: `{sentiment}` · Template: `{template}`")

                TEMPLATE_PREVIEWS = {
                    "licensing": (
                        "Thank you for reaching out about your license. Our team has been notified and will "
                        "process this as priority. During the 14-day grace period your existing backups continue to run. "
                        "To activate your renewal: Administration → License → Add License and enter your activation code."
                    ),
                    "backup_failure": (
                        "We've received your backup failure report. Steps to check right now: "
                        "(1) Job Controller in Command Center for the full error log, "
                        "(2) Look up your CV error code in the Commvault error reference, "
                        "(3) Verify port 8400 is open between client and CommServe."
                    ),
                    "restore_request": (
                        "Your restore request has been received and assigned to our recovery team. "
                        "For immediate self-service: Command Center → Protect → Restores → Browse and Restore. "
                        "For VM restore: Protect → Virtual Machines → select your VM."
                    ),
                    "access_issue": (
                        "For immediate help: click Forgot Password on the login page. "
                        "If your account is locked after failed attempts, wait 15 minutes or have your admin "
                        "go to Security → Users → Unlock. For MFA issues, verify your device clock is synced."
                    ),
                    "performance": (
                        "Slow backups are usually caused by: antivirus scanning active backup streams, "
                        "network bottleneck between client and MediaAgent, or too many concurrent jobs. "
                        "Start with the Commvault Health Report: Reports → Health Report."
                    ),
                    "billing": (
                        "Thank you for your billing inquiry. Our billing team has been notified and will "
                        "review your account within one business day. Please have your account number "
                        "and invoice number ready. Find these at cloud.commvault.com → Billing."
                    ),
                }
                with st.expander("📄 Auto-response preview"):
                    st.info(TEMPLATE_PREVIEWS.get(intent, "A general acknowledgment with documentation links would be sent."))

                if tier == "enterprise" and sentiment == "frustrated":
                    st.warning("⚡ Enterprise + frustrated sentiment → CC account manager automatically")

        with col2:
            st.subheader("Quick test emails")
            test_cases = [
                ("License expiring in 3 days",       "Our Commvault license expires in 3 days — account ACC-44821"),
                ("CV-12345 backup error",             "Error CV-12345 on nightly backup of SQL Server DB01"),
                ("Can't log in — locked out",         "Locked out of Command Center after too many failed login attempts"),
                ("Backups taking 12h instead of 2h",  "Performance severely degraded since last week — 12hr backup windows"),
                ("Incorrect charge on invoice",       "We were billed $2,400 but expected $1,900 per our contract"),
                ("VM restore failing",                "Restore of web-app-01 from last night's backup fails with CV-8892"),
                ("Exchange backup CV-4521",           "Exchange mailbox backup failing for 3 days, error CV-4521"),
                ("Want to speak to a manager",        "I am very frustrated and want to escalate to a manager immediately"),
            ]
            for subj_t, body_t in test_cases:
                if st.button(subj_t, use_container_width=True, key=f"test_{subj_t[:12]}"):
                    intent_t, esc_t = classify(f"{subj_t} {body_t}")
                    action_t = "escalated" if esc_t else "auto_responded"
                    save_email_log("demo@example.com", subj_t, intent_t, action_t,
                                   f"{intent_t}_ack.html" if not esc_t else None)
                    st.rerun()

    with tab2:
        st.subheader("Batch simulation")
        st.caption("Simulate a batch of incoming emails and see how they'd be processed")

        batch_size = st.slider("Emails to simulate", 5, 50, 20)
        if st.button("Run batch simulation →", use_container_width=True):
            sample_subjects = [
                ("Backup failed CV-12345", "backup_failure"),
                ("License expired renewal needed", "licensing"),
                ("Cannot login to Command Center", "access_issue"),
                ("Backup running slow 12 hours", "performance"),
                ("Need to restore VM web-app-01", "restore_request"),
                ("Invoice discrepancy January", "billing"),
                ("Agent install on Linux servers", "installation"),
                ("Configure Cleanroom Recovery", "restore_request"),
                ("Exchange backup CV-4521 error", "backup_failure"),
                ("VM replication not working", "performance"),
            ]
            results = {"auto_responded": 0, "escalated": 0}
            for i in range(batch_size):
                subj, expected_intent = sample_subjects[i % len(sample_subjects)]
                intent, esc = classify(subj)
                action = "escalated" if esc else "auto_responded"
                results[action] += 1
                save_email_log(f"customer{i}@company.com", subj, intent, action,
                               f"{intent}_ack.html" if not esc else None)

            col_a, col_b = st.columns(2)
            col_a.metric("Auto-responded", results["auto_responded"])
            col_b.metric("Escalated",      results["escalated"])
            st.success(f"Processed {batch_size} emails. Automation rate: {results['auto_responded']/batch_size*100:.0f}%")

    with tab3:
        st.subheader("Recent email log")
        c = db()
        logs = c.execute("SELECT * FROM email_log ORDER BY created_at DESC LIMIT 50").fetchall()
        c.close()
        if logs:
            log_data = [dict(r) for r in logs]
            st.dataframe(log_data, use_container_width=True, hide_index=True)
            csv_log = io.StringIO()
            fields = ["id","sender","subject","intent","action","template","sentiment","created_at"]
            w = csv.DictWriter(csv_log, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(log_data)
            st.download_button("⬇ Export email log", csv_log.getvalue(), file_name="email_log.csv", mime="text/csv")
        else:
            st.info("No emails processed yet.")


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📊 Analytics":
    import plotly.graph_objects as go
    import plotly.express as px

    st.title("📊 Analytics")
    st.caption("Support performance metrics · trend analysis · KB gap detection")

    col_p, col_r = st.columns([3, 1])
    with col_p:
        period = st.selectbox("Period", [7, 14, 30, 90], format_func=lambda x: f"Last {x} days", label_visibility="collapsed")
    with col_r:
        if st.button("↻ Refresh"):
            st.rerun()

    data = get_full_analytics(period)

    k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
    k1.metric("Tickets",         data["total"])
    k2.metric("Automation %",    f"{data['automation_rate']}%")
    k3.metric("Escalation %",    f"{data['escalation_rate']}%")
    k4.metric("Resolution %",    f"{data['resolution_rate']}%")
    k5.metric("Avg CSAT",        f"{data['avg_csat']:.1f}/5" if data["avg_csat"] else "—")
    k6.metric("KB Confidence",   f"{data['avg_confidence']:.0%}")
    k7.metric("Open P1",         data["open_p1"])

    if data["escalation_rate"] > 35:
        st.markdown(f'<div class="alert-banner">⚠️ High escalation rate ({data["escalation_rate"]}%) — consider expanding the knowledge base for frequently escalated intents.</div>', unsafe_allow_html=True)
    if data["avg_confidence"] > 0 and data["avg_confidence"] < 0.5:
        st.markdown(f'<div class="alert-banner">⚠️ Low average KB confidence ({data["avg_confidence"]:.0%}) — KB documents may need updating or expanding.</div>', unsafe_allow_html=True)

    st.divider()
    tab1, tab2, tab3, tab4 = st.tabs(["Volume & Trends", "Intent & Priority", "CSAT & Quality", "KB Gap Report"])

    with tab1:
        st.subheader("Daily ticket volume")
        daily = data.get("daily", [])
        if daily:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=[d["date"] for d in daily], y=[d["total"] for d in daily], name="Total", marker_color="#B5D4F4", opacity=0.8))
            fig.add_trace(go.Bar(x=[d["date"] for d in daily], y=[d["bot"] for d in daily], name="Bot resolved", marker_color="#1F4E79"))
            fig.add_trace(go.Scatter(x=[d["date"] for d in daily], y=[d["escalated"] for d in daily], name="Escalated", mode="lines+markers", line=dict(color="#dc3545", width=2)))
            fig.update_layout(barmode="overlay", height=300, margin=dict(l=0,r=0,t=0,b=0), legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Status breakdown")
            statuses = data.get("statuses", {})
            if statuses:
                fig = px.pie(values=list(statuses.values()), names=list(statuses.keys()),
                             color_discrete_sequence=["#1F4E79","#2E75B6","#9DC3E6","#BDD7EE","#DEEAF1"], hole=0.45)
                fig.update_layout(height=240, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("Priority breakdown")
            priorities = data.get("priorities", {})
            if priorities:
                colors = {"P1":"#dc3545","P2":"#fd7e14","P3":"#ffc107","P4":"#6c757d"}
                fig = go.Figure(go.Bar(
                    x=list(priorities.keys()), y=list(priorities.values()),
                    marker_color=[colors.get(k,"#888") for k in priorities.keys()]
                ))
                fig.update_layout(height=240, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Tickets by intent")
        intents = data.get("intents", [])
        if intents:
            fig = px.bar(x=[i["count"] for i in intents], y=[i["intent"] for i in intents],
                         orientation="h", color=[i["count"] for i in intents], color_continuous_scale="Blues",
                         text=[i["count"] for i in intents])
            fig.update_layout(height=320, margin=dict(l=0,r=0,t=0,b=0), showlegend=False, coloraxis_showscale=False)
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Email processing breakdown")
        email_actions = data.get("email_actions", {})
        if email_actions:
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                fig = px.pie(values=list(email_actions.values()), names=list(email_actions.keys()),
                             color_discrete_sequence=["#0F6E56","#dc3545","#ffc107"], hole=0.4)
                fig.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig, use_container_width=True)
            with col_e2:
                for action, count in email_actions.items():
                    icon = "✅" if action == "auto_responded" else "⚡"
                    st.metric(f"{icon} {action.replace('_',' ').title()}", count)

    with tab3:
        st.subheader("CSAT distribution")
        csat_dist = data.get("csat_distribution", {})
        if csat_dist:
            stars = [f"{'★'*int(k)}{'☆'*(5-int(k))}" for k in csat_dist.keys()]
            fig = go.Figure(go.Bar(x=stars, y=list(csat_dist.values()),
                                   marker_color=["#dc3545","#fd7e14","#ffc107","#9DC3E6","#0F6E56"]))
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.info("CSAT ratings are collected automatically after chatbot responses. Encourage customers to rate.")
        else:
            st.info("No CSAT ratings collected yet. CSAT prompts appear after chatbot responses.")

        st.subheader("Confidence distribution over time")
        c = db()
        conf_data = c.execute(
            "SELECT DATE(created_at), AVG(confidence), COUNT(*) FROM events "
            "WHERE created_at >= ? AND confidence IS NOT NULL GROUP BY DATE(created_at) ORDER BY 1",
            [(datetime.now()-timedelta(days=period)).isoformat()]
        ).fetchall()
        c.close()
        if conf_data:
            dates, confs, counts = zip(*conf_data)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=list(dates), y=[round(c,3) for c in confs], mode="lines+markers",
                                     name="Avg confidence", line=dict(color="#1F4E79", width=2)))
            fig.add_hline(y=0.35, line_dash="dash", line_color="#dc3545", annotation_text="Escalation threshold")
            fig.update_layout(height=220, margin=dict(l=0,r=0,t=0,b=0), yaxis_range=[0,1])
            st.plotly_chart(fig, use_container_width=True)

    with tab4:
        st.subheader("KB coverage gaps")
        st.caption("Queries that escalated due to low KB confidence — these represent missing documentation")
        gaps = data.get("kb_gaps", [])
        if gaps:
            for g in gaps:
                conf = g["avg_confidence"]
                bar = "🔴" if conf < 0.25 else "🟡" if conf < 0.45 else "🟢"
                severity = "Critical" if conf < 0.25 else "Medium" if conf < 0.45 else "Low"
                col_a, col_b, col_c = st.columns([2, 1, 1])
                col_a.markdown(f"{bar} **{g['intent']}**")
                col_b.markdown(f"Frequency: {g['frequency']}x")
                col_c.markdown(f"Avg conf: {conf:.0%} ({severity})")

            st.markdown('<div class="insight-card">💡 <b>Recommendation:</b> Add more KB documents for the top 3 gap intents. Each new document typically reduces escalation rate by 5-8% for that intent.</div>', unsafe_allow_html=True)

            c = db()
            recent_gaps = c.execute(
                "SELECT query, intent, confidence, created_at FROM kb_gaps ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            c.close()
            if recent_gaps:
                with st.expander("Recent unanswered queries"):
                    for r in recent_gaps:
                        st.markdown(f"- `{r[1]}` ({r[2]:.0%}) — *{r[0][:80]}*")
        else:
            st.success("No significant KB gaps detected for this period.")

    st.divider()
    csv_export = tickets_to_csv(load_tickets(limit=1000))
    st.download_button("⬇ Export all tickets to CSV", csv_export, file_name=f"all_tickets_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📚 Knowledge Base":
    st.title("📚 Knowledge Base")
    st.caption("10 Commvault KB documents · FAISS vector index · HuggingFace embeddings")

    index_dir  = Path("data/kb_index")
    index_exists = index_dir.exists() and (index_dir / "index.faiss").exists()

    c1, c2, c3 = st.columns(3)
    c1.metric("Documents", len(KB_DOCS))
    c2.metric("Index",     "✅ Built" if index_exists else "⏳ Not built")
    c3.metric("Embedding", "all-MiniLM-L6-v2 · free · local")

    tab1, tab2, tab3 = st.tabs(["Browse KB", "Add Document", "Test Retrieval"])

    with tab1:
        search_kb = st.text_input("Search KB documents", placeholder="backup error, restore, licensing...", label_visibility="collapsed")
        for filename, content in KB_DOCS.items():
            if search_kb and search_kb.lower() not in content.lower() and search_kb.lower() not in filename.lower():
                continue
            words = len(content.split())
            chunks = max(1, words // 175)
            with st.expander(f"📄 {filename}  ·  ~{words} words  ·  ~{chunks} chunks"):
                st.text_area("Content preview", value=content[:600]+"...", height=150,
                             disabled=True, key=f"kb_prev_{filename}", label_visibility="collapsed")

    with tab2:
        st.subheader("Upload a document")
        st.caption("TXT or MD files. Immediately available to the chatbot after upload.")
        uploaded = st.file_uploader("Drop a file here", type=["txt", "md"])

        if uploaded:
            col_cat, col_btn = st.columns([2, 1])
            with col_cat:
                category = st.selectbox("Category", ["backup","restore","licensing","access","performance","configuration","general"])

            if not groq_key:
                st.error("Add your Groq API key in the sidebar first.")
            elif col_btn and st.button("Add to knowledge base →", use_container_width=True):
                with st.spinner(f"Indexing {uploaded.name}..."):
                    from langchain.text_splitter import RecursiveCharacterTextSplitter
                    from langchain.schema import Document
                    from langchain_community.embeddings import HuggingFaceEmbeddings
                    from langchain_community.vectorstores import FAISS

                    text    = uploaded.read().decode("utf-8", errors="replace")
                    chunks  = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=80).split_documents([
                        Document(page_content=text, metadata={"source_file": uploaded.name, "category": category})
                    ])
                    embeds  = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2",
                                                     model_kwargs={"device":"cpu"}, encode_kwargs={"normalize_embeddings":True})
                    index_dir.mkdir(parents=True, exist_ok=True)

                    if index_dir.exists() and (index_dir/"index.faiss").exists():
                        existing = FAISS.load_local(str(index_dir), embeds, allow_dangerous_deserialization=True)
                        existing.add_documents(chunks)
                        existing.save_local(str(index_dir))
                    else:
                        FAISS.from_documents(chunks, embeds).save_local(str(index_dir))

                    build_kb.clear()

                st.success(f"✅ {len(chunks)} chunks from **{uploaded.name}** indexed. Chatbot updated immediately.")

        st.divider()
        if st.button("🔄 Rebuild entire index from scratch", use_container_width=True):
            import shutil
            if index_dir.exists():
                shutil.rmtree(index_dir)
            build_kb.clear()
            st.success("Index cleared. It will rebuild automatically on next chatbot query.")
            st.rerun()

    with tab3:
        st.subheader("Test retrieval")
        st.caption("Verify what the chatbot would return for any query before the interview")
        test_q = st.text_input("Test query", placeholder="What does CV-12345 mean?", label_visibility="collapsed")

        if st.button("Test →", use_container_width=True) and test_q:
            if not groq_key or store is None:
                st.error("API key and KB must be ready.")
            else:
                with st.spinner("Querying..."):
                    result = rag_query(test_q, store, groq_key)
                conf = result["confidence"]
                action = result["action"]
                lat = result["latency_ms"]

                col_r1, col_r2, col_r3 = st.columns(3)
                col_r1.metric("Confidence", f"{conf:.0%}")
                col_r2.metric("Action",     action)
                col_r3.metric("Latency",    f"{lat}ms")

                if result.get("sources"):
                    st.markdown("**Sources retrieved:**")
                    for s in result["sources"][:5]:
                        st.markdown(f"- `{s['source']}`")

                if action == "RESPOND":
                    st.markdown("**Response:**")
                    st.info(result["content"][:800])
                else:
                    st.warning(result["content"])

        st.divider()
        st.subheader("Batch coverage test")
        st.caption("Test the KB against a set of common queries to measure coverage")
        if st.button("Run coverage test →", use_container_width=True) and store and groq_key:
            test_queries = [
                ("backup_failure",  "What does CV-12345 mean?"),
                ("backup_failure",  "Backup job failed at 3AM"),
                ("restore_request", "How do I restore a virtual machine?"),
                ("restore_request", "What is Cleanroom Recovery?"),
                ("licensing",       "My license has expired"),
                ("access_issue",    "I can't log in to Command Center"),
                ("performance",     "Why are my backups running slowly?"),
                ("general",         "How does Air Gap Protect work?"),
                ("general",         "What ports does Commvault use?"),
                ("general",         "How do I set up Microsoft 365 backup?"),
            ]
            results = []
            progress = st.progress(0)
            for i, (expected_intent, query) in enumerate(test_queries):
                r = rag_query(query, store, groq_key)
                results.append({
                    "Query": query[:50], "Expected": expected_intent,
                    "Action": r["action"], "Confidence": f"{r['confidence']:.0%}",
                    "Pass": "✅" if r["action"] == "RESPOND" else "⚡"
                })
                progress.progress((i + 1) / len(test_queries))

            pass_rate = sum(1 for r in results if r["Pass"] == "✅") / len(results) * 100
            st.metric("Coverage score", f"{pass_rate:.0f}%", help="% of test queries answered confidently by the KB")
            st.dataframe(results, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.caption("Configure AEGIS behavior without touching code")

    tab1, tab2, tab3, tab4 = st.tabs(["Model & RAG", "Routing Rules", "SLA Thresholds", "About"])

    with tab1:
        st.subheader("Model configuration")
        settings = st.session_state.settings

        new_model = st.selectbox("Groq model", [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ], index=0)

        new_threshold = st.slider("Confidence threshold", 0.10, 0.80, float(settings["confidence_threshold"]), 0.05,
                                   help="Queries below this confidence escalate instead of answering. Lower = more answers, higher hallucination risk.")
        new_tokens  = st.slider("Max response tokens",  200, 1200, int(settings["max_tokens"]), 50)
        new_topk    = st.slider("Retrieved chunks (k)", 3, 10, int(settings["top_k"]), 1,
                                 help="Number of KB chunks retrieved per query. More = broader context, slower.")

        st.markdown(f'<div class="insight-card">💡 <b>Current settings:</b> model={settings["model"]}, threshold={settings["confidence_threshold"]}, k={settings["top_k"]}, max_tokens={settings["max_tokens"]}</div>', unsafe_allow_html=True)

        if st.button("Apply settings →", use_container_width=True):
            st.session_state.settings.update({
                "model": new_model,
                "confidence_threshold": new_threshold,
                "max_tokens": new_tokens,
                "top_k": new_topk,
            })
            st.success("✅ Settings applied. Changes take effect on the next query.")

    with tab2:
        st.subheader("Routing rules")
        st.caption("These rules run after intent classification and can override the defaults.")

        routing_path = Path("config/routing_rules.yaml")
        if routing_path.exists():
            current_yaml = routing_path.read_text()
            new_yaml = st.text_area("Edit routing_rules.yaml", value=current_yaml, height=400, label_visibility="collapsed")
            if st.button("Save routing rules →"):
                routing_path.parent.mkdir(parents=True, exist_ok=True)
                routing_path.write_text(new_yaml)
                st.success("✅ Routing rules saved.")
        else:
            st.info("routing_rules.yaml not found. It will be created when you first run the full backend stack.")
            default_rules = """rules:
  - name: enterprise_backup_to_senior
    trigger_field: tier
    trigger_operator: eq
    trigger_value: enterprise
    action_type: route
    action_params: '{"team": "senior_backup_team"}'
    is_active: true

  - name: production_down_p1
    trigger_field: body
    trigger_operator: contains
    trigger_value: production
    action_type: set_priority
    action_params: '{"priority": "P1"}'
    is_active: true"""
            st.text_area("Default rules (will be created on save)", value=default_rules, height=250, label_visibility="collapsed")
            if st.button("Create routing_rules.yaml →"):
                routing_path.parent.mkdir(parents=True, exist_ok=True)
                routing_path.write_text(default_rules)
                st.success("✅ Created config/routing_rules.yaml")

    with tab3:
        st.subheader("SLA thresholds (hours)")
        st.caption("How long each priority level has before breaching SLA")
        col_p1, col_p2, col_p3, col_p4 = st.columns(4)
        new_sla = {}
        new_sla["P1"] = col_p1.number_input("P1 (Critical)", value=4,  min_value=1,  max_value=24)
        new_sla["P2"] = col_p2.number_input("P2 (High)",     value=24, min_value=4,  max_value=72)
        new_sla["P3"] = col_p3.number_input("P3 (Medium)",   value=72, min_value=24, max_value=168)
        new_sla["P4"] = col_p4.number_input("P4 (Low)",      value=168,min_value=72, max_value=720)
        if st.button("Apply SLA settings →"):
            SLA_HOURS.update(new_sla)
            st.success("✅ SLA thresholds updated.")

    with tab4:
        st.subheader("About AEGIS")
        st.markdown("""
**AEGIS** (AI-powered Enterprise Governance & Intelligence for Support) is a production-grade
support automation platform built specifically for the Commvault AI & Support Automation Intern role.

**Architecture:**
- Zero-cost LLM: Groq Llama 3.3 70B (free tier, ~400 tok/sec)
- Local embeddings: HuggingFace all-MiniLM-L6-v2 (no API, runs on CPU)
- Vector search: FAISS with confidence-gated escalation
- Database: SQLite (standalone) / PostgreSQL (full stack)
- Scheduler: APScheduler background jobs
- Framework: Streamlit (standalone) / FastAPI (full stack)

**Coverage:** Every JD responsibility is a working feature.
Chatbot · Email Automation · Ticketing · Knowledge Base ·
Workflow Routing · Follow-Up Reminders · Analytics & Reporting

**Built by:** Harsha Venkateshwara · MS CS&E, University at Buffalo · F-1 OPT
        """)

        st.divider()
        st.subheader("Data management")
        c = db()
        ticket_count = c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        event_count  = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        email_count  = c.execute("SELECT COUNT(*) FROM email_log").fetchone()[0]
        gap_count    = c.execute("SELECT COUNT(*) FROM kb_gaps").fetchone()[0]
        c.close()

        st.markdown(f"**Tickets:** {ticket_count} · **Events:** {event_count} · **Emails:** {email_count} · **KB gaps logged:** {gap_count}")

        if st.button("⚠️ Clear all data (demo reset)", use_container_width=True):
            c = db()
            c.executescript("DELETE FROM tickets; DELETE FROM events; DELETE FROM email_log; DELETE FROM kb_gaps; DELETE FROM csat_ratings;")
            c.commit(); c.close()
            st.success("All demo data cleared.")
            st.rerun()