import os

# Build paths inside the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- ENVIRONMENT DETECTION ---
# VPS par start karte waqt 'RUNNING_ON_VPS' ko "True" set karein. 
# Local par ye False rahega, isliye development settings chalengi.
IS_PRODUCTION = os.environ.get('RUNNING_ON_VPS') == "True"

SECRET_KEY = '!^pl^(esc16%iofqa$k!2)!h_c*uedsi66(9ucvz1k-y=2ltk5'

if IS_PRODUCTION:
    DEBUG = False
    ALLOWED_HOSTS = ['187.127.147.81', 'smartscheduler.tech', 'www.smartscheduler.tech']
    
    # SSL & Security Settings for VPS
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = ['https://smartscheduler.tech', 'https://www.smartscheduler.tech']
else:
    DEBUG = True
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']
    
    # SSL turned off for Localhost
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    CSRF_TRUSTED_ORIGINS = ['http://localhost', 'http://127.0.0.1']

# --- APPLICATION DEFINITION ---

INSTALLED_APPS = [
    'account',
    'ttgen',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'projttgs.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'ttgen.context_processors.subscription_nav',
            ],
        },
    },
]

WSGI_APPLICATION = 'projttgs.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static/')]
STATIC_ROOT = os.path.join(BASE_DIR, 'assets')

CRISPY_TEMPLATE_PACK = 'bootstrap4'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'admindash'
LOGOUT_URL = 'logout'
LOGOUT_REDIRECT_URL = 'login'



# Email Config
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
X_FRAME_OPTIONS = "SAMEORIGIN"
