from datetime import datetime
from time import localtime, strftime
from socket import socket
from flask import (
    render_template,
    session,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from . import main
from .forms import NameForm, EditProfileForm, EditProfileAdminForm
from .. import db
from flask_login import login_required, current_user
from ..models import User, Friendships, Role
from ..decorators import admin_required, permission_required
from sqlalchemy import create_engine, text
import os
from flask_socketio import SocketIO, send, emit, join_room, leave_room
from app import socketio, ROOMS
import time

@main.route('/test', methods=['GET', 'POST'])
def test():
   return  render_template('test.html', username=current_user.username, rooms=ROOMS)


@main.route("/unknown", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        search = request.form["search"]
        data = User.query.order_by(User.username).all()
        friend_requests = Friendships.query.filter_by(
            friend_id=current_user.id, request_status=0
        ).all()
        numfr = len(friend_requests)
        return render_template("index.html", data=data, search=search, numfr=numfr)
    friend_requests = Friendships.query.filter_by(
        friend_id=current_user.id, request_status=0
    ).all()
    numfr = len(friend_requests)
    return render_template(
        "index.html",
        name=session.get("name"),
        known=session.get("known", False),
        current_time=datetime.utcnow(),
        numfr=numfr,
    )


@main.route("/friend-requests", methods=["GET", "POST"])
def friend_requests():
    ids = Friendships.query.filter_by(friend_id=current_user.id, request_status=0).all()
    ids_list = []
    for fid in ids:
        ids_list.append(fid.user_id)
    users = User.query.all()
    numfr = len(ids)
    return render_template(
        "friend_requests.html", users=users, ids_list=ids_list, numfr=numfr
    )


@main.route("/send-friend-request/<username>", methods=["GET", "POST"])
@login_required
def send_friend_request(username):
    user = User.query.filter_by(username=username).first()
    current_user.send_friend_request(user)
    db.session.commit()
    return redirect(url_for(".user", username=username))


@main.route("/send-friend-request-s/<username>", methods=["GET", "POST"])
@login_required
def send_friend_request_s(username):
    user = User.query.filter_by(username=username).first()
    current_user.send_friend_request(user)
    db.session.commit()
    return redirect(url_for(".index"))


@main.route("/confirm-request/<username>")
@login_required
def confirm_request(username):
    user = User.query.filter_by(username=username).first()
    current_user.confirm_request(user)
    db.session.commit()
    return redirect(url_for(".friend_requests"))


@main.route("/remove-request/<username>")
@login_required
def remove_request(username):
    user = User.query.filter_by(username=username).first()
    current_user.remove_request(user)
    db.session.commit()
    return redirect(url_for(".friend_requests"))


@main.route("/remove_friend/<username>")
@login_required
def remove_friend(username):
    user = User.query.filter_by(username=username).first()
    current_user.remove_friend(user)
    db.session.commit()
    return redirect(url_for(".user", username=username))


@main.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "POST":
        search = request.form["search"]
        data = User.query.order_by(User.username).all()
        return render_template("search.html", data=data, search=search)
    return render_template("search.html")


@main.route("/user/<username>")
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    friend_requests = Friendships.query.filter_by(
        friend_id=current_user.id, request_status=0
    ).all()
    numfr = len(friend_requests)
    return render_template("user.html", user=user, numfr=numfr)


@main.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user._get_current_object())
        db.session.commit()
        flash("Your profile has been updated.")
        return redirect(url_for(".user", username=current_user.username))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template("edit_profile.html", form=form)


@main.route("/edit-profile/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        db.session.commit()
        flash("The profile has been updated.")
        return redirect(url_for(".user", username=user.username))
    form.email.data = user.email
    form.username.data = user.username
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template("edit_profile.html", form=form, user=user)


@main.route("/friends/<username>")
def friends(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash("Invalid user")
        return redirect(url_for(".index"))
    page = request.args.get("page", 1, type=int)
    pagination = user.friends.paginate(
        page, per_page=current_app.config["FLASKY_FRIENDS_PER_PAGE"], error_out=False
    )
    friends = [
        {"user": item.friend, "timestamp": item.timestamp} for item in pagination.items
    ]
    return render_template(
        "friends.html",
        user=user,
        title="Friends",
        endpoint=".friends",
        pagination=pagination,
        friends=friends,
    )


@main.route("/", methods=["GET", "POST"])
@login_required
def chat():

    return render_template("chat.html", username=current_user.username, rooms=ROOMS)


@socketio.on("incoming-msg")
def on_message(data):
    """Broadcast messages"""

    msg = data["msg"]
    username = data["username"]
    room = data["room"]
    # Set timestamp
    time_stamp = time.strftime("%b-%d %I:%M%p", time.localtime())
    send({"username": username, "msg": msg, "time_stamp": time_stamp}, room=room)


@socketio.on("join")
def on_join(data):
    """User joins a room"""

    username = data["username"]
    room = data["room"]
    join_room(room)

    # Broadcast that new user has joined
    send({"msg": username + " has joined the " + room + " room."}, room=room)


@socketio.on("leave")
def on_leave(data):
    """User leaves a room"""

    username = data["username"]
    room = data["room"]
    leave_room(room)
    send({"msg": username + " has left the room"}, room=room)
