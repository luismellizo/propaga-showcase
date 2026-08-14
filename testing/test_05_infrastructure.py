import unittest
import os
import sys
import redis
from django.conf import settings
from utils import setup_django

setup_django()

from apps.users.models import User
from allauth.socialaccount.models import SocialApp

class TestInfrastructure(unittest.TestCase):
    """
    Checks the health of the system infrastructure:
    - Database Connectivity
    - Redis (Broker) Connectivity
    - File System Permissions (Media)
    - Social Configuration
    """

    def setUp(self):
        print(f"\n🏗️  Testing Infrastructure Health...")

    def test_database_connection(self):
        """Verify we can read from the DB."""
        try:
            count = User.objects.count()
            print(f"[✅ PASS] Database Connected. User count: {count}")
        except Exception as e:
            self.fail(f"[❌ FAIL] Database Connection Error: {str(e)}")

    def test_redis_connection(self):
        """Verify connectivity to Redis broker."""
        try:
            # Parse settings.CELERY_BROKER_URL or use default
            broker_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
            r = redis.from_url(broker_url)
            r.ping()
            print(f"[✅ PASS] Redis Connected at {broker_url}")
        except Exception as e:
            self.fail(f"[❌ FAIL] Redis Connection Error: {str(e)}")

    def test_media_permissions(self):
        """Verify we can write to MEDIA_ROOT."""
        media_root = settings.MEDIA_ROOT
        test_file = os.path.join(media_root, 'perm_test.txt')
        
        # Ensure dir exists
        os.makedirs(media_root, exist_ok=True)

        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            print(f"[✅ PASS] Write Permissions OK for {media_root}")
        except Exception as e:
            self.fail(f"[❌ FAIL] Write Permission Error in {media_root}: {str(e)}")

    def test_social_apps_config(self):
        """Verify SocialApps are configured in DB."""
        apps = SocialApp.objects.all()
        if not apps.exists():
            print(f"[⚠️ WARN] No SocialApps found in DB. Social propagation will fail.")
        else:
            names = ", ".join([app.name for app in apps])
            print(f"[✅ PASS] SocialApps Found: {names}")

if __name__ == '__main__':
    unittest.main()
