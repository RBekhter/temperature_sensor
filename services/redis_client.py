from redis.asyncio import Redis

redis = Redis.from_url("redis://localhost", decode_responses=True)