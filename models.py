import peewee
import peewee_async
from datetime import datetime

from settings import DB_NAME


db = peewee_async.PooledPostgresqlDatabase(DB_NAME, max_connections=20)
manager = peewee_async.Manager(db)


class Base(peewee.Model):
    class Meta:
        database = db


class User(Base):
    uid = peewee.PrimaryKeyField()
    name = peewee.CharField()
    username = peewee.CharField(null=True)
    registration = peewee.DateTimeField(default=datetime.now)
    admin = peewee.BooleanField(default=False)


class Group(Base):
    id = peewee.BigIntegerField(primary_key=True)
    name = peewee.CharField()
    link = peewee.CharField()


class UserToGroup(Base):
    user = peewee.ForeignKeyField(User, related_name='to_user', on_delete='CASCADE')
    group = peewee.ForeignKeyField(Group, related_name='to_group', on_delete='CASCADE')


if __name__ == "__main__":
    db.create_tables([User, Group, UserToGroup])