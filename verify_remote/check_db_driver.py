import importlib.util

for name in ("pymysql", "MySQLdb", "mysql.connector"):
    print(name, "OK" if importlib.util.find_spec(name) else "NO")
