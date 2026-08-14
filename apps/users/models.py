# Usuario custom desde el dia uno: cambiar AUTH_USER_MODEL despues de la
# primera migracion es una de las cosas mas caras de revertir en Django.
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    pass