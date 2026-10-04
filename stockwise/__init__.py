"""
StockWise project package.

PyMySQL shim: Django's MySQL backend talks to the low-level "MySQLdb" API.
mysqlclient (the C library it expects) needs compiler toolchains that are
painful on Windows/macOS, so we use PyMySQL - a 100% pure-Python MySQL
client - and register it as "MySQLdb". Result: zero compilation, identical
behaviour on macOS, Windows and Linux.
"""
import pymysql

pymysql.install_as_MySQLdb()
# PyMySQL >= 2.x spoofs an old mysqlclient version which Django rejects.
# Restore a version Django accepts (API used is fully compatible).
pymysql.version_info = (1, 4, 6, "final", 0)
