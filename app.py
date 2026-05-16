import threading
from dotenv import load_dotenv
load_dotenv()
from flask_mail import Mail, Message
import random
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Listing, Booking, BookingStatus, Review
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'rentify-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///rentify.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
# ── Email config ──
app.config['MAIL_SERVER'] = 'smtp-relay.brevo.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_SENDER', 'aryan.stark0325@gmail.com')
# ── Platform fee config ──
PLATFORM_FEE_PERCENT = 10  # platform keeps 10% of rental amount
PLATFORM_UPI_ID = "9955985803@axl"  # your personal UPI ID here
PLATFORM_NAME = "Rentify"
ADMIN_EMAIL = "aryan.stark0325@gmail.com"

db.init_app(app)
mail = Mail(app)
otp_store = {}   # DSA: hash map to store {email: otp}
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ── DSA: check allowed file extension using a set (O(1) lookup) ──
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# ── DSA: linear search + filter + sort on listings ──
def search_and_filter(listings, query='', category='', sort_by='newest'):
    # linear search through listings
    if query:
        query = query.lower()
        listings = [l for l in listings if query in l.title.lower() 
                    or query in l.description.lower()]

    # filter by category
    if category and category != 'All':
        listings = [l for l in listings if l.category == category]

    # sorting
    if sort_by == 'price_low':
        listings = sorted(listings, key=lambda l: l.rate_per_day)
    elif sort_by == 'price_high':
        listings = sorted(listings, key=lambda l: l.rate_per_day, reverse=True)
    elif sort_by == 'newest':
        listings = sorted(listings, key=lambda l: l.created_at, reverse=True)

    return listings

# ── DSA: build category frequency map (hash map) ──
def get_category_counts(listings):
    freq = {}
    for l in listings:
        freq[l.category] = freq.get(l.category, 0) + 1
    return freq

# ─── home ─────────────────────────────────────────────────────
@app.route('/')
def home():
    all_listings = Listing.query.filter_by(is_available=True).all()

    query = request.args.get('q', '')
    category = request.args.get('category', '')
    sort_by = request.args.get('sort', 'newest')

    listings = search_and_filter(all_listings, query, category, sort_by)
    category_counts = get_category_counts(all_listings)

    return render_template('home.html',
                           listings=listings,
                           query=query,
                           category=category,
                           sort_by=sort_by,
                           category_counts=category_counts)

# ─── register step 1: send otp ────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email'].lower().strip()
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('register'))

        # DSA: generate 6-digit OTP and store in hash map
        otp = str(random.randint(100000, 999999))
        otp_store[email] = {
            'otp': otp,
            'name': name,
            'password': generate_password_hash(password)
        }

        def send_async_email(app, msg):
            with app.app_context():
                try:
                    mail.send(msg)
                    app.logger.info('Email sent successfully')
                except Exception as e:
                    app.logger.error(f'Async mail error: {e}')

        try:
            msg = Message('Rentify — Verify your email', recipients=[email])
            msg.body = f'Hi {name},\n\nYour OTP is: {otp}\n\nDo not share it.\n\n— Team Rentify'
            thread = threading.Thread(target=send_async_email, args=(app, msg))
            thread.start()
            flash('OTP sent to your email. Please verify.')
            return redirect(url_for('verify_otp', email=email))
        except Exception as e:
            app.logger.error(f'Mail error: {e}')
            flash('Could not send OTP. Please try again.')
            return redirect(url_for('register'))

    return render_template('register.html')

# ─── register step 2: verify otp ─────────────────────────────
@app.route('/verify-otp/<email>', methods=['GET', 'POST'])
def verify_otp(email):
    if request.method == 'POST':
        entered_otp = request.form['otp'].strip()
        record = otp_store.get(email)

        if not record:
            flash('Session expired. Please register again.')
            return redirect(url_for('register'))

        if entered_otp == record['otp']:
            # OTP correct — create user
            is_admin = (email == ADMIN_EMAIL)
            user = User(
                name=record['name'],
                email=email,
                password=record['password'],
                is_admin=is_admin
            )
            db.session.add(user)
            db.session.commit()
            del otp_store[email]   # DSA: remove from hash map after use
            flash('Email verified! You can now login.')
            return redirect(url_for('login'))
        else:
            flash('Wrong OTP. Please try again.')

    return render_template('verify_otp.html', email=email)# ─── login ────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].lower().strip()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid email or password.')
    return render_template('login.html')

# ─── logout ───────────────────────────────────────────────────
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

# ─── create listing ───────────────────────────────────────────
@app.route('/listing/new', methods=['GET', 'POST'])
@login_required
def new_listing():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        category = request.form['category']
        rate_per_day = float(request.form['rate_per_day'])
        deposit = float(request.form['deposit'])
        min_days = int(request.form['min_days'])
        max_days = int(request.form['max_days'])

        image_file = 'default.jpg'
        image = request.files.get('image')
        if image and image.filename != '' and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image.save(save_path)
            image_file = filename
        elif image and image.filename != '' and not allowed_file(image.filename):
            flash('Invalid file type. Please upload a jpg, png, or gif.')
            return redirect(url_for('new_listing'))

        listing = Listing(
            title=title, description=description, category=category,
            rate_per_day=rate_per_day, deposit=deposit,
            min_days=min_days, max_days=max_days,
            image_file=image_file, lender_id=current_user.id
        )
        db.session.add(listing)
        db.session.commit()
        flash('Item listed successfully!')
        return redirect(url_for('home'))
    return render_template('new_listing.html')

# ─── view listing ─────────────────────────────────────────────
@app.route('/listing/<int:listing_id>')
def view_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    # DSA: collect booked date ranges for display
    booked_ranges = []
    for b in listing.bookings:
        if b.status not in [BookingStatus.CANCELLED.value, BookingStatus.COMPLETED.value]:
            booked_ranges.append({
                'start': b.start_date.strftime('%d %b %Y'),
                'end': b.end_date.strftime('%d %b %Y')
            })
    return render_template('view_listing.html', listing=listing, booked_ranges=booked_ranges, now=datetime.now())

# ─── book item ────────────────────────────────────────────────
@app.route('/listing/<int:listing_id>/book', methods=['POST'])
@login_required
def book_item(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
    days = (end_date - start_date).days

    if days <= 0:
        flash('End date must be after start date.')
        return redirect(url_for('view_listing', listing_id=listing_id))

    if days < listing.min_days or days > listing.max_days:
        flash(f'Booking must be between {listing.min_days} and {listing.max_days} days.')
        return redirect(url_for('view_listing', listing_id=listing_id))

    # DSA: interval overlap detection
    existing = Booking.query.filter_by(listing_id=listing_id).all()
    for b in existing:
        if b.status not in [BookingStatus.CANCELLED.value, BookingStatus.COMPLETED.value]:
            if not (end_date <= b.start_date or start_date >= b.end_date):
                flash('Item is already booked for those dates.')
                return redirect(url_for('view_listing', listing_id=listing_id))

    # ── Fee calculation ──
    rental_amount = days * listing.rate_per_day
    platform_fee = round(rental_amount * PLATFORM_FEE_PERCENT / 100, 2)
    lender_payout = round(rental_amount - platform_fee, 2)
    total_cost = round(rental_amount + listing.deposit, 2)

    booking = Booking(
        start_date=start_date, end_date=end_date,
        total_cost=total_cost,
        rental_amount=rental_amount,
        platform_fee=platform_fee,
        lender_payout=lender_payout,
        borrower_id=current_user.id,
        listing_id=listing_id
    )
    db.session.add(booking)
    db.session.commit()
    flash(f'Booking request sent! Total payable: ₹{total_cost}')
    return redirect(url_for('dashboard'))

# ─── dashboard ────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    my_listings = Listing.query.filter_by(lender_id=current_user.id).all()
    my_bookings = Booking.query.filter_by(borrower_id=current_user.id).all()

    # DSA: separate incoming requests and active rentals
    incoming = []
    active_rentals = []
    for listing in my_listings:
        for booking in listing.bookings:
            if booking.status == BookingStatus.PENDING.value:
                incoming.append(booking)
            elif booking.status == BookingStatus.APPROVED.value:
                active_rentals.append(booking)

    # DSA: booking stats hash map
    stats = {'pending': 0, 'approved': 0, 'completed': 0, 'cancelled': 0}
    for b in my_bookings:
        if b.status in stats:
            stats[b.status] += 1

    # DSA: calculate pending payout (approved + payment confirmed but not yet settled)
    pending_payout = 0
    total_earnings = 0
    for listing in my_listings:
        for booking in listing.bookings:
            if booking.payment_confirmed:
                total_earnings += booking.lender_payout
            if booking.payment_confirmed and not booking.payout_released:
                pending_payout += booking.lender_payout

    # DSA: check which listings are currently booked
    booked_listing_ids = set()
    for listing in my_listings:
        for booking in listing.bookings:
            if booking.status in [BookingStatus.APPROVED.value, BookingStatus.ACTIVE.value]:
                booked_listing_ids.add(listing.id)

    return render_template('dashboard.html',
                           my_listings=my_listings,
                           my_bookings=my_bookings,
                           incoming=incoming,
                           active_rentals=active_rentals,
                           stats=stats,
                           pending_payout=pending_payout,
                           total_earnings=total_earnings,
                           booked_listing_ids=booked_listing_ids)

# ─── approve / reject ─────────────────────────────────────────
@app.route('/booking/<int:booking_id>/approve')
@login_required
def approve_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = BookingStatus.APPROVED.value
    db.session.commit()
    flash('Booking approved!')
    return redirect(url_for('dashboard'))

@app.route('/booking/<int:booking_id>/reject')
@login_required
def reject_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = BookingStatus.CANCELLED.value
    db.session.commit()
    flash('Booking rejected.')
    return redirect(url_for('dashboard'))

# ─── edit listing ─────────────────────────────────────────────
@app.route('/listing/<int:listing_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.lender_id != current_user.id:
        flash('You can only edit your own listings.')
        return redirect(url_for('home'))

    if request.method == 'POST':
        listing.title = request.form['title']
        listing.description = request.form['description']
        listing.category = request.form['category']
        listing.rate_per_day = float(request.form['rate_per_day'])
        listing.deposit = float(request.form['deposit'])
        listing.min_days = int(request.form['min_days'])
        listing.max_days = int(request.form['max_days'])

        image = request.files.get('image')
        if image and image.filename != '' and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            listing.image_file = filename
        elif image and image.filename != '' and not allowed_file(image.filename):
            flash('Invalid file type.')
            return redirect(url_for('edit_listing', listing_id=listing_id))

        db.session.commit()
        flash('Listing updated successfully!')
        return redirect(url_for('dashboard'))

    return render_template('edit_listing.html', listing=listing)

# ─── toggle listing availability ──────────────────────────────
@app.route('/listing/<int:listing_id>/toggle')
@login_required
def toggle_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.lender_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))

    # check if any active bookings exist before unlisting
    active = [b for b in listing.bookings
              if b.status in [BookingStatus.PENDING.value, BookingStatus.APPROVED.value]]
    if active and listing.is_available:
        flash('Cannot unlist — item has active or pending bookings.')
        return redirect(url_for('dashboard'))

    listing.is_available = not listing.is_available
    db.session.commit()
    status = 'listed' if listing.is_available else 'unlisted'
    flash(f'Item {status} successfully.')
    return redirect(url_for('dashboard'))

# ─── delete listing ───────────────────────────────────────────
@app.route('/listing/<int:listing_id>/delete')
@login_required
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.lender_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))

    active = [b for b in listing.bookings
              if b.status in [BookingStatus.PENDING.value, BookingStatus.APPROVED.value]]
    if active:
        flash('Cannot delete — item has active or pending bookings.')
        return redirect(url_for('dashboard'))

    db.session.delete(listing)
    db.session.commit()
    flash('Listing deleted.')
    return redirect(url_for('dashboard'))

# ─── cancel booking (borrower) ────────────────────────────────
@app.route('/booking/<int:booking_id>/cancel')
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.borrower_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))

    if booking.status not in [BookingStatus.PENDING.value, BookingStatus.APPROVED.value]:
        flash('This booking cannot be cancelled.')
        return redirect(url_for('dashboard'))

    booking.status = BookingStatus.CANCELLED.value
    db.session.commit()
    flash('Booking cancelled successfully.')
    return redirect(url_for('dashboard'))

# ─── lender requests payment ──────────────────────────────────
@app.route('/booking/<int:booking_id>/request_payment')
@login_required
def request_payment(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.listing.lender_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    if booking.status != BookingStatus.APPROVED.value:
        flash('Booking must be approved first.')
        return redirect(url_for('dashboard'))
    booking.payment_requested = True
    db.session.commit()
    flash('Payment request sent to borrower!')
    return redirect(url_for('dashboard'))

# ─── borrower sees payment page ───────────────────────────────
@app.route('/booking/<int:booking_id>/pay')
@login_required
def pay_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.borrower_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    if not booking.payment_requested:
        flash('Lender has not requested payment yet.')
        return redirect(url_for('dashboard'))
    days = (booking.end_date - booking.start_date).days
    return render_template('payment.html',
                           booking=booking,
                           days=days,
                           platform_upi=PLATFORM_UPI_ID,
                           platform_name=PLATFORM_NAME,
                           platform_fee_percent=PLATFORM_FEE_PERCENT)

# ─── borrower confirms payment ────────────────────────────────
@app.route('/booking/<int:booking_id>/confirm_payment', methods=['POST'])
@login_required
def confirm_payment(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.borrower_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    booking.status = BookingStatus.ACTIVE.value
    booking.payment_confirmed = True
    db.session.commit()
    flash('Payment confirmed! Booking is now active.')
    return redirect(url_for('booking_confirmation', booking_id=booking.id))

# ─── booking confirmation screen ──────────────────────────────
@app.route('/booking/<int:booking_id>/confirmation')
@login_required
def booking_confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.borrower_id != current_user.id:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    return render_template('booking_confirmation.html', booking=booking)

# ─── admin panel ──────────────────────────────────────────────
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Unauthorized.')
        return redirect(url_for('home'))

    all_bookings = Booking.query.all()

    pending_verification = []
    pending_payout = []
    completed = []

    for b in all_bookings:
        if b.payment_confirmed and not b.admin_verified:
            pending_verification.append(b)
        elif b.admin_verified and not b.payout_released:
            pending_payout.append(b)
        elif b.payout_released:
            completed.append(b)

    total_platform_fee = sum(b.platform_fee for b in all_bookings if b.payout_released)

    return render_template('admin.html',
                           pending_verification=pending_verification,
                           pending_payout=pending_payout,
                           completed=completed,
                           total_platform_fee=total_platform_fee)

# ─── admin verifies payment ───────────────────────────────────
@app.route('/admin/verify/<int:booking_id>')
@login_required
def admin_verify(booking_id):
    if not current_user.is_admin:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    booking = Booking.query.get_or_404(booking_id)
    booking.admin_verified = True
    db.session.commit()
    flash(f'Payment verified for Booking #{booking_id}.')
    return redirect(url_for('admin_panel'))

# ─── admin releases payout to lender ─────────────────────────
@app.route('/admin/payout/<int:booking_id>')
@login_required
def admin_payout(booking_id):
    if not current_user.is_admin:
        flash('Unauthorized.')
        return redirect(url_for('home'))
    booking = Booking.query.get_or_404(booking_id)
    booking.payout_released = True
    booking.status = BookingStatus.COMPLETED.value
    db.session.commit()
    flash(f'Payout of ₹{booking.lender_payout} marked as released to {booking.listing.lender.name}.')
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)