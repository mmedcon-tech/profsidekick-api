import os
import sys
import uuid
from datetime import datetime

# Add the backend directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.connection import SessionLocal
from app.database.models.variants import Avatar3DModel
from app.database.models.users import User

def seed_models():
    db = SessionLocal()
    try:
        # Find an admin user to set as creator (optional, can be null)
        admin_user = db.query(User).filter(User.role == 'admin').first()
        created_by = admin_user.id if admin_user else None

        models_to_seed = [
            {
                "name": "Salama",
                "description": "Emirati Female Model",
                "file_path": "/avatars/avatar-1.glb",
                "preview_image_path": "/images/avatar-female.png",
                "is_active": True
            },
            {
                "name": "Sultan",
                "description": "Emirati Male Model",
                "file_path": "/avatars/avatar-2.glb",
                "preview_image_path": "/images/avatar-male.png",
                "is_active": True
            },
            {
                "name": "Sultan (Alternative)",
                "description": "Emirati Male Alternative Model",
                "file_path": "/avatars/avatar-3.glb",
                "preview_image_path": "/images/avatar-male.png",
                "is_active": True
            },
            {
                "name": "Layla",
                "description": "Roblox-style Kids Female Model",
                "file_path": "/avatars/kids-female.glb",
                "preview_image_path": "/images/kids-female.png",
                "is_active": True
            },
            {
                "name": "Omar",
                "description": "Roblox-style Kids Male Model",
                "file_path": "/avatars/kids-male.glb",
                "preview_image_path": "/images/kids-male.png",
                "is_active": True
            }
        ]

        for model_data in models_to_seed:
            # Check if model already exists by file_path
            existing_model = db.query(Avatar3DModel).filter(Avatar3DModel.file_path == model_data["file_path"]).first()
            if not existing_model:
                new_model = Avatar3DModel(
                    id=uuid.uuid4(),
                    name=model_data["name"],
                    description=model_data["description"],
                    file_path=model_data["file_path"],
                    preview_image_path=model_data["preview_image_path"],
                    is_active=model_data["is_active"],
                    created_by=created_by,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_model)
                print(f"Seeded model: {model_data['name']}")
            else:
                print(f"Model already exists: {model_data['name']}")
        
        db.commit()
        print("Seeding complete.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding models: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_models()
