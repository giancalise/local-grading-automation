"""
test_firebase.py
Quick test to verify the service account connects to the right Firebase project.
"""
import firebase_admin
from firebase_admin import credentials, firestore

FIRESTORE_DATABASE_ID = "ai-studio-c398f7e7-ad91-4bb2-8229-ade228c29c66"

cred = credentials.Certificate('firebase-service-account.json')
firebase_admin.initialize_app(cred)
db = firestore.client(database_id=FIRESTORE_DATABASE_ID)

print("=== Checking grading_jobs collection ===")
docs = list(db.collection('grading_jobs').stream())
print(f"Found {len(docs)} document(s)")
for d in docs:
    data = d.to_dict()
    print(f"  ID: {d.id}")
    print(f"  status: {data.get('status')}")
    print(f"  assignmentId: {data.get('assignmentId')}")
    print(f"  createdBy: {data.get('createdBy')}")
    print()

print(f"Project ID: {cred.project_id}")
print(f"Database ID: {FIRESTORE_DATABASE_ID}")
