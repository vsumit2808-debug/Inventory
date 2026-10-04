"""
Custom Django system checks.

Registered automatically via InventoryConfig.ready(). Run with any
management command (runserver/migrate/check) so problems surface with a
clear hint instead of a cryptic driver error.
"""
from django.core import checks


@checks.register()
def check_mysql_crypto(app_configs, **kwargs):
    """Warn when MySQL is configured but the cryptography package is absent.

    MySQL 8's default authentication plugin (caching_sha2_password) needs
    'cryptography' for the RSA scramble. Without it PyMySQL fails at
    connect time with a scary message; this check explains the fix upfront.
    """
    from django.conf import settings

    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "mysql" not in engine:
        return []
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return [
            checks.Warning(
                "MySQL is configured but the 'cryptography' package is not installed.",
                hint=(
                    "MySQL 8's default caching_sha2_password auth needs it. "
                    "Fix with any ONE of: "
                    "(1) pip install 'cryptography<49' (prebuilt wheel, no compiler); "
                    "(2) switch the MySQL user to native auth: ALTER USER "
                    "'stockwise'@'%' IDENTIFIED WITH mysql_native_password BY 'yourpassword'; "
                    "(3) for a no-MySQL demo set DB_ENGINE=sqlite."
                ),
                id="stockwise.W001",
            )
        ]
    return []
