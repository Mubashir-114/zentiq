"""
ZENTIQ Backend Configuration Package.
Enables PyMySQL as MySQLdb for native MySQL 8.4 support on Windows.
"""
import pymysql

# Set PyMySQL compatibility version to satisfy Django's mysqlclient >= 2.2.1 check
pymysql.version_info = (2, 2, 1, 'final', 0)
pymysql.install_as_MySQLdb()
