from qdrant_client import QdrantClient
import os

# Connect to the local Qdrant database files
client = QdrantClient(path="conv-manager/smart_home_rag/data/qdrant_db")

# List all collections
collections = client.get_collections().collections
print(f"Collections: {[c.name for c in collections]}")

# Get info for the main collection
for coll in collections:
    info = client.get_collection(collection_name=coll.name)
    print(f"\nCollection: {coll.name}")
    print(f"Points count: {info.points_count}")
    
    # Scroll through some points
    points, _ = client.scroll(collection_name=coll.name, limit=5)
    print("Sample Payloads:")
    for p in points:
        print(f"- {p.payload.get('heading', 'No Heading')}: {p.payload.get('path')}")
