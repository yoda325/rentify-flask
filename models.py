from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from enum import Enum

db = SQLAlchemy()

class BookingStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    ACTIVE = "active"
    RETURNED = "returned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    upi_id = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)

    listings = db.relationship('Listing', backref='lender', lazy=True)
    bookings = db.relationship('Booking', backref='borrower', lazy=True)

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    rate_per_day = db.Column(db.Float, nullable=False)
    deposit = db.Column(db.Float, nullable=False)
    min_days = db.Column(db.Integer, default=1)
    max_days = db.Column(db.Integer, default=30)
    image_file = db.Column(db.String(200), default='default.jpg')
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bookings = db.relationship('Booking', backref='listing', lazy=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default=BookingStatus.PENDING.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    platform_fee = db.Column(db.Float, default=0.0)
    rental_amount = db.Column(db.Float, default=0.0)
    lender_payout = db.Column(db.Float, default=0.0)
    payment_confirmed = db.Column(db.Boolean, default=False)
    payment_requested = db.Column(db.Boolean, default=False)
    admin_verified = db.Column(db.Boolean, default=False)
    payout_released = db.Column(db.Boolean, default=False)

    borrower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)