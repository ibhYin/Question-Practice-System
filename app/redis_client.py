import redis

from .config import settings

# decode_responses=True：拿到 str 而不是 bytes，本项目数据量小，直接用
rdb = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True,
)
