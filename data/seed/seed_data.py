"""
Seeds the database with realistic demo tickets.
Run this to populate the UI so it looks great during a demo.

Usage:
    python seed_data.py
"""
import requests
import random
import time

API = "http://localhost:8000"

DEMO_TICKETS = [
    {
        "subject": "Backup job failed overnight — SQL Server DB01",
        "body": "Getting error CV-12345 on our nightly SQL Server backup. Job started at 2:00 AM and failed at 40% completion. This is a P1 for us as DB01 is our production database. Error log attached.",
        "customer_tier": "enterprise",
    },
    {
        "subject": "Cannot restore VM from last night's backup",
        "body": "Trying to restore VM 'web-app-01' from the backup taken at 11PM last night. The restore job starts but fails immediately with error CV-8892. We need this VM restored urgently for a client demo at 9AM.",
        "customer_tier": "premium",
    },
    {
        "subject": "License expired — 150 VMs unprotected",
        "body": "We received a notification that our Commvault Cloud license expired yesterday. Our account number is ACC-44821. We have approximately 150 VMs that are now unprotected. Please help us get a renewal processed immediately.",
        "customer_tier": "enterprise",
    },
    {
        "subject": "Command Center login not working",
        "body": "I've been locked out of the Commvault Command Center. I've tried resetting my password twice but the password reset emails aren't arriving. I need access urgently to check backup status.",
        "customer_tier": "standard",
    },
    {
        "subject": "Backup jobs taking 3x longer than usual",
        "body": "Starting about a week ago, our backup jobs that used to complete in 4 hours are now taking 12+ hours. Nothing has changed in our environment that I'm aware of. Could there be a performance issue with the backup server?",
        "customer_tier": "standard",
    },
    {
        "subject": "How do I configure Cleanroom Recovery for ransomware scenario?",
        "body": "We want to set up a Cleanroom Recovery environment to test our ransomware recovery procedures. I've read the documentation but I'm unclear on the network isolation configuration. Can someone walk me through the setup?",
        "customer_tier": "premium",
    },
    {
        "subject": "Question about invoice for January",
        "body": "I have a question about our January invoice. We were charged $2,400 but based on our contract I expected $1,900. Can someone explain the additional charges?",
        "customer_tier": "standard",
    },
    {
        "subject": "Error CV-9999 on cloud backup sync",
        "body": "Our Commvault Cloud backup sync is failing with error CV-9999. This started happening after we updated to version 11.42 last week. All other backup jobs are working fine, just the cloud sync is broken.",
        "customer_tier": "standard",
    },
    {
        "subject": "Need help installing agent on new Linux servers",
        "body": "We've provisioned 15 new Linux servers and need to install the Commvault file system agent on all of them. Is there a bulk deployment method or do we need to do each one individually?",
        "customer_tier": "standard",
    },
    {
        "subject": "PRODUCTION DOWN — all backup infrastructure offline",
        "body": "URGENT: All of our backup infrastructure is offline. CommServe is not responding. We cannot access any backup data. This is impacting production operations. Need immediate assistance.",
        "customer_tier": "enterprise",
    },
    {
        "subject": "How do I set up email alerts for failed jobs?",
        "body": "I'd like to configure email alerts so our team gets notified when any backup job fails. I can see there's an alert settings area but I'm not sure how to configure it properly.",
        "customer_tier": "trial",
    },
    {
        "subject": "Backup of Exchange mailboxes failing",
        "body": "Our Exchange mailbox backup has been failing for 3 days. Error code CV-4521. The file system backups on the same server are working fine. Microsoft Exchange EWS integration may be involved.",
        "customer_tier": "premium",
    },
]


def seed():
    print("Seeding demo tickets...")
    for i, ticket in enumerate(DEMO_TICKETS, 1):
        resp = requests.post(f"{API}/tickets", json=ticket)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  #{data['ticket_id']} [{data['priority']}] {data['category']} → {data['team']}")
        else:
            print(f"  Failed: {resp.status_code}")
        time.sleep(0.3)  # gentle on the API

    print(f"\nSeeded {len(DEMO_TICKETS)} tickets")
    print("Open the Streamlit app to see them in the Ticket Inbox.")


if __name__ == "__main__":
    seed()
