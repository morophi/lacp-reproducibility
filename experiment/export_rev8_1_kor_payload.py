import json

import create_rev8_1_kor as payload


print(json.dumps({"PARA": payload.PARA, "TABLES": payload.TABLES}, ensure_ascii=False))
