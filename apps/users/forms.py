from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class CustomSocialSignupForm(SocialSignupForm):
    """
    Signup social con los inputs del design system.

    allauth decide qué campos pide según `ACCOUNT_SIGNUP_FIELDS`, así que la clase
    se aplica sobre los widgets en vez de escribir los `<input>` a mano en el
    template: si mañana cambian los campos, siguen saliendo estilados.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            clases = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{clases} input'.strip()

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        # DEBE incluir password1 y password2 para que funcione con UserCreationForm
        fields = ("username", "email")

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = ("username", "email")