import re
from django import forms
from django.contrib.auth.models import User
from .models import Profile


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(label='Password',
                               widget=forms.PasswordInput)
    password2 = forms.CharField(label='Repeat password',
                                widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'email')

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&_\-#]).{8,}$'
            if not re.match(pattern, password):
                raise forms.ValidationError(
                    'Password must be 8+ characters and include an uppercase letter, '
                    'a lowercase letter, a digit, and a special character (@$!%*?&_-#).'
                )
        return password

    def clean_password2(self):
        cd = self.cleaned_data
        if cd.get('password') != cd.get('password2'):
            raise forms.ValidationError('Passwords don\'t match.')
        return cd['password2']

