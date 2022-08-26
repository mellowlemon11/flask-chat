from datetime import datetime
from email.policy import default
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from markdown import markdown
import bleach
from flask import current_app, request, url_for, request
from flask_login import UserMixin, AnonymousUserMixin
from app.exceptions import ValidationError
from . import db, login_manager
from sqlalchemy import select
import random, string
import sqlite3


class Permission:
    FOLLOW = 1
    COMMENT = 2
    WRITE = 4
    MODERATE = 8
    ADMIN = 16


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    users = db.relationship("User", backref="role", lazy="dynamic")

    def __init__(self, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.permissions is None:
            self.permissions = 0

    @staticmethod
    def insert_roles():
        roles = {
            "User": [Permission.FOLLOW, Permission.COMMENT, Permission.WRITE],
            "Moderator": [
                Permission.FOLLOW,
                Permission.COMMENT,
                Permission.WRITE,
                Permission.MODERATE,
            ],
            "Administrator": [
                Permission.FOLLOW,
                Permission.COMMENT,
                Permission.WRITE,
                Permission.MODERATE,
                Permission.ADMIN,
            ],
        }
        default_role = "User"
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.reset_permissions()
            for perm in roles[r]:
                role.add_permission(perm)
            role.default = role.name == default_role
            db.session.add(role)
        db.session.commit()

    def add_permission(self, perm):
        if not self.has_permission(perm):
            self.permissions += perm

    def remove_permission(self, perm):
        if self.has_permission(perm):
            self.permissions -= perm

    def reset_permissions(self):
        self.permissions = 0

    def has_permission(self, perm):
        return self.permissions & perm == perm

    def __repr__(self):
        return "Role %r>" % self.name


"""friends = db.Table(
    "friends",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id")),
    db.Column("friend_id", db.Integer, db.ForeignKey("users.id")),
    db.Column("status", db.Integer, db.ForeignKey("users.id")),
)"""


class Friendships(db.Model):
    __tablename__ = "friendships"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    friend_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    request_status = db.Column(db.Integer)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(64), unique=True, index=True)
    username = db.Column(db.String(64), unique=True, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"))
    password_hash = db.Column(db.String(128))
    confirmed = db.Column(db.Boolean, default=False)
    name = db.Column(db.String(64))
    location = db.Column(db.String(64))
    about_me = db.Column(db.Text())
    member_since = db.Column(db.DateTime(), default=datetime.utcnow)
    last_seen = db.Column(db.DateTime(), default=datetime.utcnow)
    avatar_hash = db.Column(db.String(32))
    hashtag = db.Column(db.String(32), unique=True, index=True)

    """friend = db.relationship('User',
		secondary=friends,
		primaryjoin=(friends.c.user_id==id),
		secondaryjoin=(friends.c.friend_id==id),
		backref = db.backref('user', lazy='dynamic'),
		lazy='dynamic'
		)"""

    friends = db.relationship(
        "Friendships", primaryjoin="User.id==Friendships.user_id", lazy="dynamic"
    )

    """def add_friend(self, user):
			friendsl = db.session.query(friends).filter_by(user_id=self.id,friend_id=user.id).first()
			if friendsl is None:
					self.friend.append(user)
					user.friend.append(self)
			db.session.commit()"""

    def send_friend_request(self, user):
        f = Friendships(user_id=self.id, friend_id=user.id, request_status=0)
        db.session.add(f)
        db.session.commit()

    def confirm_request(self, user):
        f = Friendships.query.filter_by(user_id=user.id, friend_id=self.id)
        for item in f:
            db.session.delete(item)
        db.session.commit()
        f = Friendships(user_id=user.id, friend_id=self.id, request_status=1)
        g = Friendships(user_id=self.id, friend_id=user.id, request_status=1)
        db.session.add(f)
        db.session.add(g)
        db.session.commit()

    def remove_request(self, user):
        f = Friendships.query.filter_by(user_id=user.id, friend_id=self.id)
        for item in f:
            db.session.delete(item)
        db.session.commit()

    def remove_friend(self, user):
        f = Friendships.query.filter_by(user_id=user.id, friend_id=self.id)
        g = Friendships.query.filter_by(user_id=self.id, friend_id=user.id)
        for item in f:
            db.session.delete(item)
        for item in g:
            db.session.delete(item)
        db.session.commit()

    def is_friends(self, user):
        return Friendships.query.filter_by(
            user_id=self.id, friend_id=user.id, request_status=1
        ).first()

    def in_request(self, user):
        return Friendships.query.filter_by(
            user_id=self.id, friend_id=user.id, request_status=0
        ).first()

    def count_friends(self):
        return Friendships.query.filter_by(user_id=self.id, request_status=1).count()

    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        if self.role is None:
            if self.email == current_app.config["FLASKY_ADMIN"]:
                self.role = Role.query.filter_by(name="Administrator").first()
            if self.role is None:
                self.role = Role.query.filter_by(default=True).first()
        if self.email is not None and self.avatar_hash is None:
            self.avatar_hash = self.gravatar_hash()

    def generate_hashtag(self):
        self.hashtag = "#" + str(random.randint(1000, 9999))

    @property
    def password(self):
        raise AttributeError("password is not a readable attribute")

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_confirmation_token(self, expiration=3600):
        s = Serializer(current_app.config["SECRET_KEY"], expiration)
        return s.dumps({"confirm": self.id}).decode("utf-8")

    def confirm(self, token):
        s = Serializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token.encode("utf-8"))
        except:
            return False
        if data.get("confirm") != self.id:
            return False
        self.confirmed = True
        db.session.add(self)
        return True

    def generate_reset_token(self, expiration=3600):
        s = Serializer(current_app.config["SECRET_KEY"], expiration)
        return s.dumps({"reset": self.id}).decode("utf-8")

    @staticmethod
    def reset_password(token, new_password):
        s = Serializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token.encode("utf-8"))
        except:
            return False
        user = User.query.get(data.get("reset"))
        if user is None:
            return False
        user.password = new_password
        db.session.add(user)
        return True

    def generate_email_change_token(self, new_email, expiration=3600):
        s = Serializer(current_app.config["SECRET_KEY"], expiration)
        return s.dumps({"change_email": self.id, "new_email": new_email}).decode(
            "utf-8"
        )

    def change_email(self, token):
        s = Serializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token.encode("utf-8"))
        except:
            return False
        if data.get("change_email") != self.id:
            return False
        new_email = data.get("new_email")
        if new_email is None:
            return False
        if self.query.filter_by(email=new_email).first() is not None:
            return False
        self.email = new_email
        self.avatar_hash = self.gravatar_hash()
        db.session.add(self)
        return True

    def can(self, perm):
        return self.role is not None and self.role.has_permission(perm)

    def is_administrator(self):
        return self.can(Permission.ADMIN)

    def ping(self):
        self.last_seen = datetime.utcnow()
        db.session.add(self)
        db.session.commit()

    def gravatar_hash(self):
        return hashlib.md5(self.email.lower().encode("utf-8")).hexdigest()

    def gravatar(self, size=100, default="identicon", rating="g"):
        url = "https://secure.gravatar.com/avatar"
        hash = self.avatar_hash or self.gravatar_hash()
        return "{url}/{hash}?s={size}&d={default}&r={rating}".format(
            url=url, hash=hash, size=size, default=default, rating=rating
        )

    def generate_auth_token(self, expiration=3600):
        s = Serializer(current_app.config["SECRET_KEY"], expires_in=expiration)
        return s.dumps({"id": self.id}).decode("utf-8")

    @staticmethod
    def verify_auth_token(token):
        s = Serializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token)
        except:
            return None
        return User.query.get(data["id"])

    def __repr__(self):
        return "<User %r>" % self.username


class AnonymousUser(AnonymousUserMixin):
    def can(self, permissions):
        return False

    def is_administrator(self):
        return False


login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
