# test_firebase.py  (save next to grading_agent.py)
import firebase_admin
from firebase_admin import credentials, firestore, storage

cred = credentials.Certificate(r"C:\Users\gce4\Documents\solidworks-mcp\firebase-service-account.json")
firebase_admin.initialize_app(cred, {"storageBucket": "gen-lang-client-0024774658.firebasestorage.app"})

db = firestore.client()
bucket = storage.bucket()

# Test Firestore write
db.collection("test").document("ping").set({"hello": "world"})
print("✓ Firestore write OK")

# Test Storage upload
bucket.blob("test/ping.txt").upload_from_string("hello")
print("✓ Storage upload OK")
print("\nAll good — agent is ready to run.")
```

Run it with `python test_firebase.py`. If both print, you're connected.

---

## Step 2 — Load sample data into Firebase

You have two things to upload: a **student .sldprt file** and a **solution .sldprt file**.

**Easiest way — Firebase Console manually:**

1. Go to **Storage** in the Firebase Console
2. Create this folder structure by uploading files:
```
submissions/
  test_quiz/
    student1.sldprt
    student2.sldprt
solution/
  test_quiz/
    solution.sldprt
results/
  test_quiz/          ← leave empty, agent writes here