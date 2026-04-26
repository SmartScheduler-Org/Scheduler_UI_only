from django.http import HttpResponse
from django.shortcuts import render
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView
from django.views.generic.edit import FormView
from .models import Profile
from .forms1 import LoginForm, UserRegistrationForm


class CustomPasswordResetView(PasswordResetView):
    """
    Overrides form_valid to inject domain_override=request.get_host().

    Django's default PasswordResetView calls get_current_site(request) which,
    when django-allauth is installed, can return the stale 'example.com' entry
    from the django_site DB table. Passing domain_override bypasses that lookup
    entirely and always uses the real host from the HTTP request.
    """
    html_email_template_name = 'registration/password_reset_email_html.html'

    def form_valid(self, form):
        form.save(
            domain_override=self.request.get_host(),
            use_https=self.request.is_secure(),
            token_generator=self.token_generator,
            from_email=self.from_email,
            email_template_name=self.email_template_name,
            subject_template_name=self.subject_template_name,
            request=self.request,
            html_email_template_name=self.html_email_template_name,
            extra_email_context=self.extra_email_context,
        )
        # Call FormView.form_valid (redirect) directly — skip
        # PasswordResetView.form_valid which would call form.save() again.
        return FormView.form_valid(self, form)


def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = authenticate(request,
                                username=cd['email'],
                                password=cd['password'])
            if user is not None:
                if user.is_active:
                    login(request, user)
                    return HttpResponse('Authenticated '\
                                        'successfully')
                else:
                    return HttpResponse('Disabled account')
            else:
                return HttpResponse('Invalid login')
    else:
        form = LoginForm()
    return render(request, 'account/login.html', {'form': form})


def register(request):
    if request.method == 'POST':
        user_form = UserRegistrationForm(request.POST)
        if user_form.is_valid():
            # Create a new user object but avoid saving it yet
            new_user = user_form.save(commit=False)
            # Set the chosen password
            new_user.set_password(
                user_form.cleaned_data['password'])
            # Save the User object
            new_user.save()
            # Create the user profile
            #Profile.objects.create(user=new_user)
            return render(request,
                          'account/register_done.html',
                          {'new_user': new_user})
    else:
        user_form = UserRegistrationForm()
    return render(request,
                  'account/register.html',
                  {'user_form': user_form})

