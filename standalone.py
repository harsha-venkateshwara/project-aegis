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

.msg-wrap { display: flex; align-items: flex-start; gap: 10px; margin: 14px 0; }
.msg-wrap.user { flex-direction: row-reverse; }
.avatar {
    width: 36px; height: 36px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: 14px;
    font-weight: 600; flex-shrink: 0;
}
.avatar.bot  { background: #1F4E79; color: white; font-size: 16px; }
.avatar.user { background: #e8f0fe; color: #1F4E79; }
.bubble {
    max-width: 76%; padding: 13px 16px; border-radius: 16px;
    line-height: 1.6; font-size: 14.5px;
}
.bubble.bot  { background: white; border: 1px solid #e0e8f0; border-bottom-left-radius: 4px; color: #1a1a1a; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.bubble.user { background: #1F4E79; color: white; border-bottom-right-radius: 4px; }
.bubble.escalate { background: #fff8e6; border: 1px solid #ffc107; border-bottom-left-radius: 4px; color: #1a1a1a; }
.bubble p { margin: 0 0 8px; }
.bubble p:last-child { margin-bottom: 0; }
.bubble ul, .bubble ol { margin: 6px 0 6px 18px; padding: 0; }
.bubble li { margin: 3px 0; }
.msg-meta { font-size: 11px; color: #999; margin-top: 5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.msg-meta.user { justify-content: flex-end; }
.conf-bar { display: inline-flex; align-items: center; gap: 5px; }
.conf-track { width: 60px; height: 5px; background: #e0e0e0; border-radius: 3px; overflow: hidden; }
.conf-fill { height: 100%; border-radius: 3px; }
.conf-high  { background: #0F6E56; }
.conf-mid   { background: #BA7517; }
.conf-low   { background: #dc3545; }
.source-card {
    display: inline-flex; align-items: center; gap: 5px;
    background: #EBF3FB; color: #1F4E79; border: 1px solid #B5D4F4;
    padding: 3px 9px; border-radius: 20px; font-size: 11.5px;
    margin: 2px; font-weight: 500;
}
.source-card span { font-size: 13px; }
.action-bar { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.action-btn {
    background: none; border: 1px solid #d0d8e4; color: #555;
    padding: 4px 10px; border-radius: 20px; font-size: 11.5px; cursor: pointer;
}
.action-btn:hover { background: #f0f4f8; border-color: #1F4E79; color: #1F4E79; }
.ticket-card {
    background: white; border: 1.5px solid #1F4E79; border-radius: 12px;
    padding: 14px 16px; margin-top: 10px; max-width: 340px;
}
.ticket-card h4 { margin: 0 0 8px; color: #1F4E79; font-size: 13px; }
.ticket-row { display: flex; justify-content: space-between; font-size: 12px; margin: 4px 0; }
.ticket-label { color: #888; }
.ticket-val { font-weight: 600; color: #1a1a1a; }
.priority-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 700; }
.p1 { background: #fce8e8; color: #A32D2D; }
.p2 { background: #fff0e0; color: #854F0B; }
.p3 { background: #fffbe6; color: #7a6200; }
.welcome-hero { text-align: center; padding: 32px 24px 24px; }
.welcome-hero h2 { font-size: 22px; color: #1F4E79; margin-bottom: 8px; }
.welcome-hero p { color: #666; font-size: 14px; margin-bottom: 24px; }
.cap-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; max-width: 560px; margin: 0 auto 24px; text-align: left; }
.cap-card { background: white; border: 1px solid #e0e8f0; border-radius: 10px; padding: 12px 14px; }
.cap-card b { color: #1F4E79; font-size: 13px; }
.cap-card p { color: #666; font-size: 12px; margin: 3px 0 0; }
.topic-grid { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-width: 600px; margin: 0 auto; }
.topic-pill {
    background: #E6F1FB; color: #1F4E79; border: 1px solid #B5D4F4;
    padding: 7px 14px; border-radius: 20px; font-size: 13px; cursor: pointer;
    transition: all 0.15s;
}
.followup-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px 46px; }
.followup-pill {
    background: #f0f4f8; border: 1px solid #c8d8e8; color: #1F4E79;
    padding: 6px 14px; border-radius: 20px; font-size: 12.5px; cursor: pointer;
}
.chat-status-bar {
    display: flex; align-items: center; gap: 12px; padding: 8px 12px;
    background: #f8fafb; border-radius: 8px; margin-bottom: 8px;
    font-size: 12px; color: #666; border: 1px solid #e0e8f0;
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #0F6E56; flex-shrink: 0; }
.typing-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #888; margin: 0 2px;
    animation: typing-bounce 1.2s infinite;
}
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
    30% { transform: translateY(-5px); opacity: 1; }
}
.csat-row { display: flex; gap: 6px; margin-top: 8px; align-items: center; }
.csat-row span { font-size: 12px; color: #888; }
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


# API key

def get_groq_key() -> str:
    try:
        k = st.secrets.get("GROQ_API_KEY", "")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", st.session_state.get("groq_key", ""))


# Database

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


# Intent classifier

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
    "hi", "hey", "hello", "hiya", "howdy", "sup", "yo", "yoo", "yooo",
    "ok", "okay", "cool", "great", "got it", "bye", "goodbye",
    "thanks", "thank you", "good morning", "good afternoon", "good evening",
    "thx", "ty", "wassup", "what's up", "whats up", "how's it going",
    "hows it going", "how are you", "how r u", "what's good", "whats good",
    "heya", "greetings", "salutations", "morning", "evening", "afternoon",
    "good day", "nice to meet you", "pleased to meet you",
}

GREETING_PHRASES = [
    "how's it", "how are", "what's up", "wassup", "how r u",
    "good to", "nice to", "pleasure to", "how do you do",
    "hope you", "trust you", "checking in",
]

SMALL_TALK = [
    "how's it going", "what's going on", "how's everything",
    "just checking in", "touching base", "hope all is well",
    "hope you're well", "how are things",
]


def classify(text: str) -> tuple[str, bool]:
    t = text.lower().strip()

    if t in GREETINGS or (len(t.split()) <= 3 and any(g in t for g in GREETINGS)):
        return "_greeting", False

    if len(t.split()) <= 8 and any(phrase in t for phrase in GREETING_PHRASES):
        return "_greeting", False

    if any(phrase in t for phrase in SMALL_TALK):
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


# Knowledge base documents

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


# RAG pipeline

@st.cache_resource(show_spinner=False)
def build_kb(_groq_key: str):
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document

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
        intent_q, escalate_q = classify(question)

        # General chat/greetings — respond conversationally
        if intent_q in ("_greeting", "general_inquiry") and not escalate_q:
            client = Groq(api_key=groq_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "You are AEGIS, an AI support assistant for Commvault. "
                        "You are helpful, friendly, and professional. "
                        "For general questions respond naturally. You can discuss any topic. "
                        "Keep responses concise and warm."
                    )},
                    {"role": "user", "content": question},
                ],
                max_tokens=300, temperature=0.7,
            )
            return {
                "content": response.choices[0].message.content,
                "action": "RESPOND", "confidence": 0.8,
                "sources": [], "latency_ms": round((_time.time() - t0) * 1000),
            }

        # Real support issue with no KB coverage — escalate
        _save_kb_gap(question, intent_q, confidence)
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
        intent_q, escalate_q = classify(question)

        # General conversation — respond naturally via Groq streaming
        if intent_q in ("_greeting", "general_inquiry") and not escalate_q:
            client = Groq(api_key=groq_key)
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "You are AEGIS, a friendly AI assistant for Commvault support. "
                        "For general questions respond naturally and helpfully. "
                        "You can discuss any topic. Keep responses concise and warm."
                    )},
                    {"role": "user", "content": question},
                ],
                max_tokens=300, temperature=0.7, stream=True,
            )
            def general_tokens():
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
            return general_tokens(), 0.8, [], "RESPOND"

        # Real support question with no KB coverage — escalate
        _save_kb_gap(question, intent_q, confidence)
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


# Database helpers

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


# Initialise

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


# Sidebar

with st.sidebar:
    st.markdown("## 🛡️ AEGIS")
    st.caption("AI Support Automation Engine\nCommvault ·")
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



# DASHBOARD

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



# CHATBOT

elif page == "💬 Chatbot":

    tier_now = st.session_state.get("tier", "standard")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;padding:8px 14px;background:#f8fafb;border:1px solid #e0e8f0;border-radius:8px;margin-bottom:12px;font-size:12px;color:#666">'
        f'<div style="width:8px;height:8px;border-radius:50%;background:#0F6E56;flex-shrink:0"></div>'
        f'<span>AEGIS &nbsp;·&nbsp; Groq Llama 3.3 70B</span>'
        f'<span>·</span><span>KB: {len(KB_DOCS)} documents</span>'
        f'<span>·</span><span>Tier: <b>{tier_now}</b></span>'
        f'<span style="margin-left:auto;color:#0F6E56;font-weight:600">● Online</span></div>',
        unsafe_allow_html=True
    )

    SRC_ICONS = {
        "backup_errors.txt": "🔧", "restore_procedures.txt": "♻️",
        "licensing.txt": "🔑", "access_troubleshooting.txt": "🔐",
        "performance_tuning.txt": "⚡", "commvault_cloud_saas.txt": "☁️",
        "command_center_guide.txt": "🖥️", "disaster_recovery.txt": "🛡️",
        "network_configuration.txt": "🌐", "vm_protection.txt": "💻",
    }

    def _conf_bar_html(conf):
        pct = int(conf * 100)
        col = "#0F6E56" if conf >= 0.65 else "#BA7517" if conf >= 0.40 else "#dc3545"
        label = "High" if conf >= 0.65 else "Medium" if conf >= 0.40 else "Low"
        return (
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="width:64px;height:5px;background:#e8e8e8;border-radius:3px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{col};border-radius:3px"></div></div>'
            f'<span style="font-size:11px;color:#888">{pct}% {label}</span></div>'
        )

    def _source_chips_html(sources):
        chips = ""
        for s in sources[:4]:
            src = s.get("source", "")
            icon = SRC_ICONS.get(src, "📄")
            name = src.replace(".txt","").replace("_"," ").title()
            chips += (
                f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'background:#E6F1FB;color:#1F4E79;border:1px solid #B5D4F4;'
                f'padding:3px 10px;border-radius:20px;font-size:11.5px;margin:2px;font-weight:500">'
                f'{icon} {name}</span>'
            )
        return chips

    def _ticket_card_html(ticket_id, priority, team, intent):
        p_style = {
            "P1": "background:#fce8e8;color:#A32D2D",
            "P2": "background:#fff0e0;color:#854F0B",
            "P3": "background:#fffbe6;color:#7a6200",
        }.get(priority, "background:#f0f0f0;color:#555")
        team_display = team.replace("_", " ").title()
        intent_display = intent.replace("_", " ").title()
        return (
            f'<div style="background:white;border:2px solid #1F4E79;border-radius:12px;padding:14px 18px;margin-top:12px;max-width:360px">'
            f'<div style="color:#1F4E79;font-weight:700;font-size:13.5px;margin-bottom:10px">📋 Support Ticket Created</div>'
            f'<div style="display:flex;justify-content:space-between;font-size:12.5px;padding:4px 0;border-bottom:1px solid #f0f0f0"><span style="color:#888">Ticket ID</span><span style="font-weight:600">#{ticket_id}</span></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;font-size:12.5px;padding:4px 0;border-bottom:1px solid #f0f0f0"><span style="color:#888">Priority</span><span style="padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700;{p_style}">{priority}</span></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:12.5px;padding:4px 0;border-bottom:1px solid #f0f0f0"><span style="color:#888">Assigned to</span><span style="font-weight:600">{team_display}</span></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:12.5px;padding:4px 0"><span style="color:#888">Category</span><span style="font-weight:600">{intent_display}</span></div>'
            f'<div style="margin-top:10px;font-size:12px;color:#0F6E56;font-weight:500">✅ A specialist will reach out within SLA</div>'
            f'</div>'
        )

    def render_message(msg, idx):
        role = msg["role"]
        content = msg.get("content", "")
        action = msg.get("action", "RESPOND")
        conf = msg.get("confidence", 0)
        lat = msg.get("latency_ms", 0)
        sources = msg.get("sources", [])
        ticket_id = msg.get("ticket_id")
        ts = msg.get("ts", "")
        intent_val = msg.get("intent", "general_inquiry")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(content)
                if ts:
                    st.markdown(f'<div style="font-size:10.5px;color:rgba(0,0,0,0.35);margin-top:2px">{ts}</div>', unsafe_allow_html=True)

        else:
            with st.chat_message("assistant", avatar="🛡️"):
                if action == "ESCALATE":
                    st.warning(f"**⚡ Escalated to support team**\n\n{content}")
                    if ticket_id:
                        priority_v = PRIORITY_MAP.get(intent_val, "P2")
                        team_v = TEAM_MAP.get(intent_val, "general_support")
                        st.markdown(_ticket_card_html(ticket_id, priority_v, team_v, intent_val), unsafe_allow_html=True)
                else:
                    st.markdown(content)

                if action == "RESPOND":
                    if sources:
                        st.markdown(f'<div style="margin-top:10px">{_source_chips_html(sources)}</div>', unsafe_allow_html=True)
                    meta = _conf_bar_html(conf) + f'<span style="font-size:11px;color:#ccc;margin:0 6px">·</span><span style="font-size:11px;color:#888">{lat}ms &nbsp;·&nbsp; Groq Llama 3.3 &nbsp;·&nbsp; {ts}</span>'
                    st.markdown(f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:8px">{meta}</div>', unsafe_allow_html=True)

                if msg.get("show_csat"):
                    st.markdown('<div style="margin-top:10px;font-size:12px;color:#666;font-weight:500">Rate this response:</div>', unsafe_allow_html=True)
                    star_cols = st.columns([1, 1, 1, 1, 1, 5])
                    labels = ["Poor", "Fair", "Good", "Great", "Excellent"]
                    for star in range(1, 6):
                        with star_cols[star - 1]:
                            if st.button("★", key=f"csat_{ticket_id}_{star}_{idx}", help=labels[star-1]):
                                save_csat(ticket_id or 0, st.session_state.session_id, star)
                                msg["show_csat"] = False
                                st.rerun()

    if not st.session_state.messages:
        st.markdown(
            '<div style="text-align:center;padding:36px 20px 28px">'
            '<div style="font-size:48px;margin-bottom:12px">🛡️</div>'
            '<div style="font-size:24px;font-weight:700;color:#1F4E79;margin-bottom:8px">Hello, I\'m AEGIS</div>'
            '<div style="font-size:14px;color:#666;line-height:1.7;max-width:520px;margin:0 auto 24px">'
            'Your AI-powered Commvault support assistant. I can answer questions,<br>'
            'troubleshoot issues, and connect you with a specialist when needed — 24/7.'
            '</div></div>',
            unsafe_allow_html=True
        )

        cap_html = (
            '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;max-width:680px;margin:0 auto 28px">'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">🔧 Backup Errors</b><p style="color:#666;font-size:12px;margin:4px 0 0">CV error codes, failed jobs, scheduling issues</p></div>'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">♻️ Restore & Recovery</b><p style="color:#666;font-size:12px;margin:4px 0 0">Files, VMs, databases, Cleanroom ransomware</p></div>'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">🔑 Licensing</b><p style="color:#666;font-size:12px;margin:4px 0 0">Activation, renewals, grace periods</p></div>'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">⚡ Performance</b><p style="color:#666;font-size:12px;margin:4px 0 0">Slow backups, MediaAgent tuning, network</p></div>'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">🔐 Access & Login</b><p style="color:#666;font-size:12px;margin:4px 0 0">Password reset, MFA, SSO, role permissions</p></div>'
            '<div style="background:white;border:1px solid #e0e8f0;border-radius:10px;padding:13px 15px"><b style="color:#1F4E79;font-size:13px">☁️ Commvault Cloud</b><p style="color:#666;font-size:12px;margin:4px 0 0">M365, Azure, AWS, Air Gap Protect</p></div>'
            '</div>'
        )
        st.markdown(cap_html, unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;font-size:13px;color:#999;margin-bottom:16px">Try one of these common topics:</div>', unsafe_allow_html=True)

        topic_groups = [
            ["Backup job failed with CV-12345", "How do I restore a VM?", "What is Cleanroom Recovery?"],
            ["My license has expired", "Can't log in to Command Center", "Backups are running very slowly"],
            ["Set up Microsoft 365 backup", "How does Air Gap Protect work?", "CommServe DR backup setup"],
        ]
        for group in topic_groups:
            tcols = st.columns(3)
            for i, topic in enumerate(group):
                with tcols[i]:
                    if st.button(topic, use_container_width=True, key=f"topic_{hashlib.md5(topic.encode()).hexdigest()[:6]}"):
                        st.session_state.messages.append({"role":"user","content":topic,"ts":datetime.now().strftime("%H:%M")})
                        intent, escalate = classify(topic)
                        if escalate or store is None or not groq_key:
                            result = {"content":"Connecting you with a specialist.","action":"ESCALATE","confidence":1.0,"sources":[],"latency_ms":0,"intent":intent}
                        else:
                            result = rag_query(topic, store, groq_key)
                            result["intent"] = intent
                        result["ts"] = datetime.now().strftime("%H:%M")
                        st.session_state.messages.append({"role":"assistant",**result,"show_csat":result.get("action")=="RESPOND","msg_idx":len(st.session_state.messages)})
                        if result.get("action") == "RESPOND" and groq_key:
                            st.session_state.followups = get_followups(topic, result.get("content",""), groq_key)
                        save_event(st.session_state.session_id, intent, result["confidence"], result["action"], result["latency_ms"])
                        st.rerun()

    else:
        for idx, msg in enumerate(st.session_state.messages):
            render_message(msg, idx)

        if st.session_state.followups:
            st.markdown('<div style="margin:14px 0 6px;font-size:12.5px;color:#888;font-weight:500">💡 You might also want to ask:</div>', unsafe_allow_html=True)
            fu_cols = st.columns(min(len(st.session_state.followups), 3))
            for i, suggestion in enumerate(st.session_state.followups):
                with fu_cols[i % 3]:
                    if st.button(suggestion, key=f"fu_{i}_{suggestion[:8]}", use_container_width=True):
                        st.session_state.followups = []
                        st.session_state.messages.append({"role":"user","content":suggestion,"ts":datetime.now().strftime("%H:%M")})
                        intent, escalate = classify(suggestion)
                        if escalate or store is None or not groq_key:
                            st.session_state.messages.append({"role":"assistant","content":"Connecting you with a specialist.","action":"ESCALATE","confidence":1.0,"sources":[],"latency_ms":0,"ts":datetime.now().strftime("%H:%M")})
                        else:
                            gen, conf_fu, srcs_fu, action_fu = stream_rag_query(suggestion, store, groq_key)
                            with st.chat_message("assistant", avatar="🛡️"):
                                full_fu = st.write_stream(gen)
                            st.session_state.messages.append({"role":"assistant","content":full_fu,"action":action_fu,"confidence":conf_fu,"sources":srcs_fu,"latency_ms":0,"ts":datetime.now().strftime("%H:%M"),"show_csat":action_fu=="RESPOND","msg_idx":len(st.session_state.messages)})
                            if action_fu == "RESPOND":
                                st.session_state.followups = get_followups(suggestion, full_fu, groq_key)
                        save_event(st.session_state.session_id, intent, conf_fu if not escalate else 1.0, "ESCALATE" if escalate else action_fu, 0)
                        st.rerun()

    st.divider()

    toolbar_left, toolbar_tier, toolbar_clear, toolbar_export = st.columns([4, 1.2, 0.8, 0.8])
    with toolbar_tier:
        st.selectbox("Tier", ["standard","premium","enterprise","trial"], key="tier", label_visibility="collapsed")
    with toolbar_clear:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state.messages = []
            st.session_state.followups = []
            st.session_state.session_id = f"s-{int(time.time())}"
            st.rerun()
    with toolbar_export:
        if st.session_state.messages:
            export_text = "\n\n".join(
                f"[{m.get('ts','')}] {'You' if m['role']=='user' else 'AEGIS'}: {m.get('content','')}"
                for m in st.session_state.messages
            )
            st.download_button("⬇️", export_text, file_name=f"aegis_{datetime.now().strftime('%Y%m%d_%H%M')}.txt", use_container_width=True, help="Export conversation")

    user_input = st.chat_input("Ask AEGIS anything about Commvault — backup, restore, licensing, performance, access...")

    if user_input:
        st.session_state.followups = []
        ts_now = datetime.now().strftime("%H:%M")
        st.session_state.messages.append({"role":"user","content":user_input,"ts":ts_now})
        intent, escalate = classify(user_input)

        if not groq_key:
            st.session_state.messages.append({"role":"assistant","content":"Add your Groq API key in the sidebar to enable the chatbot.","action":"ERROR","confidence":0,"sources":[],"latency_ms":0,"ts":ts_now})

        elif escalate or store is None:
            tier = st.session_state.get("tier","standard")
            priority = "P1" if tier == "enterprise" else PRIORITY_MAP.get(intent,"P2")
            team = TEAM_MAP.get(intent,"senior_support")
            tid = save_ticket(user_input[:100], user_input, intent, priority, team, 1.0, "chatbot", tier, "chat_escalation")
            reply = "I've connected you with our support team. A specialist will reach out shortly based on your SLA tier."
            st.session_state.messages.append({
                "role":"assistant","content":reply,"action":"ESCALATE",
                "confidence":1.0,"sources":[],"latency_ms":0,"ts":ts_now,
                "ticket_id":tid,"intent":intent,"show_csat":False,
                "msg_idx":len(st.session_state.messages),
            })
            save_event(st.session_state.session_id, intent, 1.0, "ESCALATE", 0)

        else:
            import time as _t
            t0 = _t.time()
            gen, conf, srcs, action = stream_rag_query(user_input, store, groq_key)
            with st.chat_message("assistant", avatar="🛡️"):
                full_response = st.write_stream(gen)
            lat = round((_t.time() - t0) * 1000)

            tid = None
            if action == "ESCALATE":
                tier = st.session_state.get("tier","standard")
                tid = save_ticket(user_input[:100], user_input, intent, PRIORITY_MAP.get(intent,"P2"), TEAM_MAP.get(intent,"senior_support"), conf, "chatbot", tier, "low_confidence")

            st.session_state.messages.append({
                "role":"assistant","content":full_response,"action":action,
                "confidence":conf,"sources":srcs,"latency_ms":lat,"ts":ts_now,
                "ticket_id":tid,"intent":intent,
                "show_csat": action == "RESPOND",
                "msg_idx":len(st.session_state.messages),
            })
            if action == "RESPOND" and groq_key:
                st.session_state.followups = get_followups(user_input, full_response, groq_key)
            save_event(st.session_state.session_id, intent, conf, action, lat)

        st.rerun()



# TICKET INBOX
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



# EMAIL HUB
elif page == "📧 Email Hub":
    st.title("📧 Email Automation Hub")
    st.caption("Connect your inbox · auto-classify · template match · auto-respond or escalate")

    import imaplib
    import smtplib
    import email as email_lib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.header import decode_header

    TEMPLATE_PREVIEWS = {
        "licensing": (
            "Thank you for reaching out about your license. Our team has been notified and will "
            "process this as priority. During the 14-day grace period your existing backups continue to run. "
            "To activate your renewal: Administration → License → Add License and enter your activation code."
        ),
        "backup_failure": (
            "We received your backup failure report. Immediate steps to check:\n\n"
            "1. Open Job Controller in Command Center for the full error log\n"
            "2. Look up your CV error code in the Commvault error reference\n"
            "3. Verify port 8400 is open between client and CommServe\n"
            "4. Check MediaAgent disk space under Storage > MediaAgents\n\n"
            "A backup specialist has been notified and will follow up within your SLA window."
        ),
        "restore_request": (
            "Your restore request has been received and assigned to our recovery team. "
            "For immediate self-service: Command Center → Protect → Restores → Browse and Restore. "
            "For VM restore: Protect → Virtual Machines → select your VM → select restore point. "
            "For Cleanroom Recovery: Protect → Cleanroom Recovery → Create Cleanroom."
        ),
        "access_issue": (
            "For immediate help with your login issue:\n\n"
            "1. Click Forgot Password on the Command Center login page — reset email comes from noreply@commvault.com\n"
            "2. If locked out after failed attempts, wait 15 minutes for auto-unlock\n"
            "3. For MFA issues: verify your device clock is synced to UTC\n"
            "4. Admin unlock: Security → Users → select user → Unlock Account\n\n"
            "If the issue persists, our security team has been notified."
        ),
        "performance": (
            "Slow backups are most commonly caused by:\n\n"
            "1. Antivirus scanning active backup streams — exclude Commvault directories from AV\n"
            "2. Network bottleneck between client and MediaAgent — run bandwidth test during backup\n"
            "3. Too many concurrent streams — check MediaAgent limits under Storage > MediaAgents\n\n"
            "Start with the Health Report: Reports → Health Report → Generate. "
            "Our performance team has been assigned to your case."
        ),
        "billing": (
            "Thank you for your billing inquiry. Our billing team has been notified and will review "
            "your account within one business day. Please have your account number and invoice number ready. "
            "You can find these at cloud.commvault.com → Billing → Invoice History."
        ),
        "installation": (
            "For bulk agent deployment on multiple servers, use Command Center's push install: "
            "Protect → Add Server → enter hostname and credentials. "
            "For scripted deployment: download the agent from cloud.commvault.com and use the "
            "silent install flag: CommvaultInstaller.exe /silent /authcode YOUR_CODE. "
            "Our onboarding team will follow up to confirm successful deployment."
        ),
        "_escalate": (
            "Thank you for reaching out. Your message has been flagged as high priority and assigned "
            "directly to a senior support specialist. You will hear from us within 1 hour. "
            "Your case has been escalated."
        ),
    }

    def send_smtp_email(to_email, subject, body_text, smtp_host, smtp_port, smtp_user, smtp_pass):
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = smtp_user
            msg["To"]      = to_email
            msg.attach(MIMEText(body_text, "plain"))
            with smtplib.SMTP_SSL(smtp_host, int(smtp_port)) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())
            return True, "Sent"
        except Exception as e:
            return False, str(e)

    def fetch_imap_emails(host, user, password, limit=10):
        try:
            mail = imaplib.IMAP4_SSL(host)
            mail.login(user, password)
            mail.select("inbox")
            _, ids = mail.search(None, "UNSEEN")
            email_ids = ids[0].split()[-limit:]
            emails = []
            for eid in reversed(email_ids):
                _, data = mail.fetch(eid, "(RFC822)")
                msg = email_lib.message_from_bytes(data[0][1])
                subj_raw = decode_header(msg["Subject"] or "")[0]
                subj = subj_raw[0].decode(subj_raw[1] or "utf-8") if isinstance(subj_raw[0], bytes) else subj_raw[0]
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
                emails.append({"id": eid.decode(), "from": msg["From"] or "", "subject": subj, "body": body[:1000]})
            mail.logout()
            return emails, None
        except Exception as e:
            return [], str(e)

    def process_email_and_respond(sender, subject, body, tier, smtp_settings=None):
        full_text = f"{subject} {body}"
        intent, escalate = classify(full_text)

        # Greetings and small talk — friendly welcome, no support template
        if intent == "_greeting":
            preview = (
                "Hello! Thanks for reaching out to AEGIS Support. "
                "I'm your AI-powered Commvault support assistant. "
                "I can help with backup failures, restore procedures, licensing questions, "
                "performance issues, and access problems.\n\n"
                "What can I help you with today?"
            )
            save_email_log(sender, subject, "_greeting", "auto_responded", "greeting_response.html", "neutral")
            sent_ok, send_msg = False, ""
            if smtp_settings and smtp_settings.get("host") and smtp_settings.get("user"):
                sent_ok, send_msg = send_smtp_email(
                    sender, f"Re: {subject}", preview,
                    smtp_settings["host"], smtp_settings.get("port", 465),
                    smtp_settings["user"], smtp_settings["password"]
                )
            return {
                "intent": "_greeting", "escalate": False, "action": "auto_responded",
                "template": "greeting_response.html", "preview": preview,
                "sentiment": "neutral", "priority": "P4",
                "sent": sent_ok, "send_msg": send_msg,
            }

        # General inquiry with no clear support intent — use Groq for a smart reply
        if intent == "general_inquiry" and not escalate and groq_key:
            from groq import Groq as _Groq
            try:
                _client = _Groq(api_key=groq_key)
                _resp = _client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": (
                            "You are AEGIS, an AI support assistant for Commvault backup and data protection. "
                            "Reply to this email helpfully and professionally in 3-5 sentences. "
                            "If it mentions Commvault, give a specific helpful answer. "
                            "Otherwise be friendly and ask how you can help with their Commvault environment."
                        )},
                        {"role": "user", "content": f"Subject: {subject}\n\nBody: {body}"},
                    ],
                    max_tokens=200, temperature=0.7,
                )
                preview = _resp.choices[0].message.content
            except Exception:
                preview = (
                    "Thank you for your email. I'm AEGIS, your Commvault support assistant. "
                    "Could you share more details about your environment or the issue you're experiencing? "
                    "I'm here to help with backup failures, restore procedures, licensing, performance, and access issues."
                )
            save_email_log(sender, subject, "general_inquiry", "auto_responded", "general_response.html", "neutral")
            sent_ok, send_msg = False, ""
            if smtp_settings and smtp_settings.get("host") and smtp_settings.get("user"):
                sent_ok, send_msg = send_smtp_email(
                    sender, f"Re: {subject}", preview,
                    smtp_settings["host"], smtp_settings.get("port", 465),
                    smtp_settings["user"], smtp_settings["password"]
                )
            return {
                "intent": "general_inquiry", "escalate": False, "action": "auto_responded",
                "template": "general_response.html", "preview": preview,
                "sentiment": "neutral", "priority": "P4",
                "sent": sent_ok, "send_msg": send_msg,
            }

        # Detect sentiment for support emails
        sentiment = "neutral"
        if any(w in body.lower() for w in ["urgent","critical","asap","immediately","production down","data loss"]):
            sentiment = "frustrated"
        elif any(w in body.lower() for w in ["thank","appreciate","great","happy","love"]):
            sentiment = "positive"

        action   = "escalated" if escalate else "auto_responded"
        template = f"{intent}_ack.html" if not escalate else "_escalate_ack.html"
        preview  = TEMPLATE_PREVIEWS.get("_escalate" if escalate else intent, TEMPLATE_PREVIEWS.get("billing","We have received your request and will respond shortly."))

        priority = "P1" if (escalate or tier=="enterprise") else PRIORITY_MAP.get(intent,"P2")
        if tier == "enterprise" and sentiment == "frustrated":
            priority = "P1"

        sent_ok = False
        send_msg = ""
        if smtp_settings and smtp_settings.get("host") and smtp_settings.get("user"):
            subject_out = f"Re: {subject}"
            sent_ok, send_msg = send_smtp_email(
                sender, subject_out, preview,
                smtp_settings["host"], smtp_settings.get("port",465),
                smtp_settings["user"], smtp_settings["password"]
            )

        save_email_log(sender, subject, intent, action, template, sentiment)
        if escalate:
            save_ticket(subject[:100], body, intent, priority, TEAM_MAP.get(intent,"senior_support"), 1.0, "email", tier, "email_escalation")

        return {
            "intent": intent, "escalate": escalate, "action": action,
            "template": template, "preview": preview, "sentiment": sentiment,
            "priority": priority, "sent": sent_ok, "send_msg": send_msg,
        }

    for k,v in {"email_sender":"","email_subject":"","email_body":"","email_tier":"standard","email_result":None}.items():
        if k not in st.session_state:
            st.session_state[k] = v

    smtp_settings = None
    imap_host_val = st.session_state.get("imap_host","imap.gmail.com")
    imap_user_val = st.session_state.get("imap_user","")
    imap_pass_val = st.session_state.get("imap_pass","")
    smtp_host_val = st.session_state.get("smtp_host","smtp.gmail.com")
    smtp_port_val = st.session_state.get("smtp_port","465")
    smtp_user_val = st.session_state.get("smtp_user","")
    smtp_pass_val = st.session_state.get("smtp_pass","")
    if smtp_user_val and smtp_pass_val:
        smtp_settings = {"host":smtp_host_val,"port":smtp_port_val,"user":smtp_user_val,"password":smtp_pass_val}

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📥 Live Inbox", "✍️ Process Email", "📤 Batch Simulation", "📋 Email Log", "⚙️ Email Setup"])

    with tab1:
        st.subheader("Live Email Inbox")
        if not imap_user_val or not imap_pass_val:
            st.info("Connect your email in the **Email Setup** tab to see your real inbox here.\n\nThis tab fetches unread emails from your Gmail and processes them through the AEGIS pipeline.")
            st.markdown("""
**How it works:**
1. Add your Gmail address and App Password in Email Setup
2. AEGIS fetches unread emails via IMAP
3. Each email is classified by intent (backup failure, licensing, access issue, etc.)
4. High-confidence emails get an auto-response template
5. Uncertain or escalation emails are flagged for human review
6. All processing is logged in the Email Log tab

**To get a Gmail App Password:**
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search "App passwords" → Create one for "Mail"
4. Use that 16-character password here (not your regular Gmail password)
            """)
        else:
            col_fetch, col_limit = st.columns([3,1])
            with col_limit:
                fetch_limit = st.number_input("Fetch limit", min_value=1, max_value=50, value=10)
            with col_fetch:
                if st.button("📥 Fetch unread emails", use_container_width=True):
                    with st.spinner(f"Connecting to {imap_host_val}..."):
                        emails, err = fetch_imap_emails(imap_host_val, imap_user_val, imap_pass_val, fetch_limit)
                    if err:
                        st.error(f"IMAP connection failed: {err}")
                    elif not emails:
                        st.success("No unread emails — inbox is clear.")
                    else:
                        st.session_state["inbox_emails"] = emails
                        st.success(f"Fetched {len(emails)} unread emails")

            inbox = st.session_state.get("inbox_emails", [])
            if inbox:
                for em in inbox:
                    intent_preview, esc_preview = classify(f"{em['subject']} {em['body']}")
                    badge = "🔴 Escalate" if esc_preview else f"🟢 {intent_preview.replace('_',' ').title()}"
                    with st.expander(f"{badge} · {em['subject'][:60]} · From: {em['from'][:40]}"):
                        st.caption(f"From: {em['from']}")
                        st.text_area("Body preview", value=em["body"][:400], height=80, disabled=True, key=f"inbox_body_{em['id']}", label_visibility="collapsed")
                        tier_inbox = st.selectbox("Tier", ["standard","premium","enterprise","trial"], key=f"tier_{em['id']}")
                        if st.button(f"Process & respond →", key=f"proc_{em['id']}", use_container_width=True):
                            result = process_email_and_respond(em["from"], em["subject"], em["body"], tier_inbox, smtp_settings)
                            if result["sent"]:
                                st.success(f"✅ Auto-response sent · Intent: {result['intent']} · Priority: {result['priority']}")
                            elif smtp_settings:
                                st.error(f"Send failed: {result['send_msg']}")
                            else:
                                st.info(f"Classified as **{result['intent']}** (no SMTP configured — response not sent). Add SMTP in Email Setup to send real responses.")
                            st.session_state.setdefault("inbox_processed", set()).add(em["id"])

    with tab2:
        st.subheader("Process a single email")
        col_form, col_tests = st.columns([3, 2])

        with col_tests:
            st.markdown("**Quick test emails**")
            test_cases = [
                ("License expiring in 3 days", "customer@acmecorp.com", "Commvault license expiring in 3 days — urgent", "Our Commvault Cloud license expires in 3 days. Account ACC-44821. We have 150 VMs that will be unprotected. Please help us process renewal urgently.", "enterprise"),
                ("CV-12345 backup error", "admin@company.com", "Backup job failed overnight — error CV-12345", "Our nightly SQL Server backup failed at 3AM with error CV-12345. This is our production database DB01. We need this resolved urgently as no backups ran last night.", "enterprise"),
                ("Can't log in — locked out", "user@org.com", "Cannot access Command Center — account locked", "I have been locked out of Commvault Command Center after too many failed login attempts. I need to restore access immediately as I need to check backup status.", "standard"),
                ("Backups taking 12h instead of 2h", "ops@business.com", "Backup performance severely degraded", "Our backup jobs that used to complete in 2 hours are now taking 12+ hours. This started last week. Nothing has changed in our environment. Could there be a performance issue?", "premium"),
                ("Incorrect charge on invoice", "finance@company.com", "Invoice discrepancy — overcharged by $500", "We received our January invoice for $2,400 but based on our contract we expected $1,900. Please explain the additional $500 charge and issue a credit if incorrect.", "standard"),
                ("VM restore failing", "admin@corp.com", "Cannot restore VM web-app-01 from backup", "Restore of VM web-app-01 from last night's backup fails immediately with error CV-8892. We need this VM restored urgently for a client demo at 9AM tomorrow.", "premium"),
                ("Exchange backup CV-4521", "exchange-admin@org.com", "Exchange mailbox backup failing 3 days", "Exchange mailbox backup has been failing for 3 days with error CV-4521. The file system backups on the same server are working fine. Exchange EWS integration may be the issue.", "standard"),
                ("Want to speak to a manager", "angry-customer@company.com", "Extremely frustrated — escalating to management", "I am extremely frustrated with the lack of response. Our production environment has been at risk for 48 hours. I want to speak to a senior manager immediately. This is unacceptable.", "enterprise"),
            ]
            for label, sndr, subj, bdy, tier_t in test_cases:
                if st.button(label, use_container_width=True, key=f"test_email_{label[:10]}"):
                    st.session_state["email_sender"] = sndr
                    st.session_state["email_subject"] = subj
                    st.session_state["email_body"]    = bdy
                    st.session_state["email_tier"]    = tier_t
                    result = process_email_and_respond(sndr, subj, bdy, tier_t, smtp_settings)
                    st.session_state["email_result"] = result
                    st.rerun()

        with col_form:
            sender_v  = st.text_input("From",    value=st.session_state["email_sender"] or "customer@acmecorp.com", key="form_sender")
            subject_v = st.text_input("Subject", value=st.session_state["email_subject"] or "", placeholder="Email subject...", key="form_subject")
            body_v    = st.text_area("Body",     value=st.session_state["email_body"] or "", placeholder="Paste the email body here...", height=120, key="form_body")
            tier_v    = st.selectbox("Customer tier", ["standard","premium","enterprise","trial"],
                                     index=["standard","premium","enterprise","trial"].index(st.session_state.get("email_tier","standard")),
                                     key="form_tier")

            if st.button("Process Email →", use_container_width=True):
                if not body_v and not subject_v:
                    st.warning("Enter an email subject and body first.")
                else:
                    result = process_email_and_respond(sender_v, subject_v, body_v, tier_v, smtp_settings)
                    st.session_state["email_result"] = result
                    st.session_state["email_sender"]  = sender_v
                    st.session_state["email_subject"] = subject_v
                    st.session_state["email_body"]    = body_v
                    st.session_state["email_tier"]    = tier_v
                    st.rerun()

            result = st.session_state.get("email_result")
            if result:
                if result["escalate"]:
                    st.error(f"⚡ **Escalated** · Intent: `{result['intent']}` · Sentiment: `{result['sentiment']}` · Priority: `{result['priority']}`")
                else:
                    st.success(f"✅ **Auto-responded** · Intent: `{result['intent']}` · Sentiment: `{result['sentiment']}` · Template: `{result['template']}`")

                if smtp_settings and result.get("sent"):
                    st.success(f"📤 Real email sent to **{sender_v}**")
                elif smtp_settings and not result.get("sent"):
                    st.error(f"Send failed: {result.get('send_msg','unknown error')}")
                else:
                    st.caption("_SMTP not configured — configure in Email Setup tab to send real responses_")

                if result.get("intent") == "billing" or tier_v == "enterprise":
                    st.warning(f"⚡ Enterprise tier / billing → CC account manager automatically")

                with st.expander("📄 Auto-response preview", expanded=True):
                    st.info(result["preview"])

                with st.expander("📊 Classification details"):
                    d1, d2, d3, d4 = st.columns(4)
                    d1.metric("Intent",    result["intent"].replace("_"," ").title())
                    d2.metric("Action",    result["action"].replace("_"," ").title())
                    d3.metric("Sentiment", result["sentiment"].title())
                    d4.metric("Priority",  result["priority"])

    with tab3:
        st.subheader("Batch email simulation")
        st.caption("Simulate a realistic mix of incoming support emails and measure automation throughput")
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            batch_size = st.slider("Number of emails", 5, 100, 30)
        with col_b2:
            tier_mix = st.selectbox("Customer tier mix", ["Mixed (realistic)","All standard","All enterprise"])

        if st.button("▶ Run batch simulation", use_container_width=True):
            samples = [
                ("Backup failed CV-12345",          "backup_failure"),
                ("License expired renewal needed",   "licensing"),
                ("Cannot login to Command Center",   "access_issue"),
                ("Backup running slow 12 hours",     "performance"),
                ("Need to restore VM web-app-01",    "restore_request"),
                ("Invoice discrepancy January",      "billing"),
                ("Agent install on Linux servers",   "installation"),
                ("Configure Cleanroom Recovery",     "restore_request"),
                ("Exchange backup CV-4521 error",    "backup_failure"),
                ("VM replication not working",       "performance"),
                ("License activation code question", "licensing"),
                ("Password reset not working",       "access_issue"),
                ("Production down all backups down", "_escalate"),
                ("Feature request API export",       "feature_request"),
                ("Commvault Cloud M365 setup help",  "configuration"),
            ]
            tiers = ["standard","premium","enterprise","trial"]
            results_batch = {"auto_responded": 0, "escalated": 0, "by_intent": {}}
            pbar = st.progress(0)
            for i in range(batch_size):
                subj, _ = samples[i % len(samples)]
                tier_b = "enterprise" if tier_mix == "All enterprise" else "standard" if tier_mix == "All standard" else tiers[i % len(tiers)]
                intent_b, esc_b = classify(subj)
                action_b = "escalated" if esc_b else "auto_responded"
                results_batch[action_b] += 1
                results_batch["by_intent"][intent_b] = results_batch["by_intent"].get(intent_b, 0) + 1
                save_email_log(f"customer{i}@company.com", subj, intent_b, action_b, f"{intent_b}_ack.html" if not esc_b else None)
                pbar.progress((i+1)/batch_size)

            auto_rate = results_batch["auto_responded"] / batch_size * 100
            m1, m2, m3 = st.columns(3)
            m1.metric("Auto-responded", results_batch["auto_responded"], help="Sent auto-response")
            m2.metric("Escalated",      results_batch["escalated"],      help="Flagged for human agent")
            m3.metric("Automation rate",f"{auto_rate:.0f}%")

            st.markdown("**Breakdown by intent:**")
            for intent_name, count in sorted(results_batch["by_intent"].items(), key=lambda x: -x[1]):
                pct = count/batch_size*100
                bar_w = int(pct * 2)
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0">'
                    f'<span style="min-width:160px;font-size:13px">{intent_name.replace("_"," ").title()}</span>'
                    f'<div style="height:14px;width:{bar_w}px;background:#1F4E79;border-radius:3px"></div>'
                    f'<span style="font-size:13px;color:#666">{count} ({pct:.0f}%)</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    with tab4:
        st.subheader("Email processing log")
        c = db()
        logs = c.execute("SELECT * FROM email_log ORDER BY created_at DESC LIMIT 100").fetchall()
        c.close()
        if logs:
            log_data = [dict(r) for r in logs]
            st.dataframe(log_data, use_container_width=True, hide_index=True)
            buf = io.StringIO()
            fields = ["id","sender","subject","intent","action","template","sentiment","created_at"]
            w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(log_data)
            st.download_button("⬇ Export log CSV", buf.getvalue(), file_name="email_log.csv", mime="text/csv")
        else:
            st.info("No emails processed yet. Use the Process Email or Batch Simulation tabs.")

    with tab5:
        st.subheader("Email connection setup")
        st.caption("Configure IMAP to read real emails and SMTP to send real auto-responses")

        st.markdown("""
**Gmail setup (recommended):**
1. Enable 2-Step Verification at [myaccount.google.com](https://myaccount.google.com) → Security
2. Search "App passwords" → Generate one for **Mail**
3. Use the 16-character app password below (NOT your regular Gmail password)
4. IMAP must be enabled: Gmail Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP
        """)

        col_imap, col_smtp = st.columns(2)

        with col_imap:
            st.markdown("**📥 IMAP (incoming — read emails)**")
            imap_h = st.text_input("IMAP host",  value=imap_host_val, placeholder="imap.gmail.com")
            imap_u = st.text_input("Email address", value=imap_user_val, placeholder="you@gmail.com")
            imap_p = st.text_input("App password", value=imap_pass_val, type="password", placeholder="xxxx xxxx xxxx xxxx")
            if st.button("Test IMAP connection", use_container_width=True):
                with st.spinner("Testing..."):
                    _, err = fetch_imap_emails(imap_h, imap_u, imap_p, 1)
                if err:
                    st.error(f"Failed: {err}")
                else:
                    st.success("✅ IMAP connection successful")
                    st.session_state["imap_host"] = imap_h
                    st.session_state["imap_user"] = imap_u
                    st.session_state["imap_pass"] = imap_p

        with col_smtp:
            st.markdown("**📤 SMTP (outgoing — send responses)**")
            smtp_h = st.text_input("SMTP host",  value=smtp_host_val, placeholder="smtp.gmail.com")
            smtp_p2 = st.text_input("SMTP port", value=smtp_port_val, placeholder="465")
            smtp_u = st.text_input("Email address", value=smtp_user_val, placeholder="you@gmail.com", key="smtp_u_input")
            smtp_pw = st.text_input("App password", value=smtp_pass_val, type="password", placeholder="xxxx xxxx xxxx xxxx", key="smtp_pw_input")
            if st.button("Test SMTP connection", use_container_width=True):
                ok, msg = send_smtp_email(smtp_u, "AEGIS SMTP test", "This is a test email from AEGIS.", smtp_h, smtp_p2, smtp_u, smtp_pw)
                if ok:
                    st.success(f"✅ Test email sent to {smtp_u}")
                    st.session_state["smtp_host"] = smtp_h
                    st.session_state["smtp_port"] = smtp_p2
                    st.session_state["smtp_user"] = smtp_u
                    st.session_state["smtp_pass"] = smtp_pw
                else:
                    st.error(f"Failed: {msg}")

        if st.button("Save all email settings", use_container_width=True):
            st.session_state.update({"imap_host":imap_h,"imap_user":imap_u,"imap_pass":imap_p,"smtp_host":smtp_h,"smtp_port":smtp_p2,"smtp_user":smtp_u,"smtp_pass":smtp_pw})
            st.success("✅ Settings saved for this session. Add them to .streamlit/secrets.toml for persistence.")

        st.divider()
        st.markdown("**For .streamlit/secrets.toml (persistent across restarts):**")
        st.code("""GROQ_API_KEY = "gsk-..."
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "you@gmail.com"
IMAP_PASS = "your-app-password"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "465"
SMTP_USER = "you@gmail.com"
SMTP_PASS = "your-app-password"
""")


# ANALYTICS

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


 
# KNOWLEDGE BASE


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