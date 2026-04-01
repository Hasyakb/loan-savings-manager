# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps
import os
import hashlib

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///loan_saving.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Fix for Render PostgreSQL URL
if app.config['SQLALCHEMY_DATABASE_URI'] and app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)

db = SQLAlchemy(app)

# Database Models
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100))
    address = db.Column(db.String(200))
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    savings = db.relationship('Saving', backref='customer', lazy=True, cascade='all, delete-orphan')
    loans = db.relationship('Loan', backref='customer', lazy=True, cascade='all, delete-orphan')
    proxy_collections = db.relationship('ProxyCollection', backref='customer', lazy=True)
    
    def total_savings(self):
        total = sum(s.amount for s in self.savings if s.transaction_type == 'deposit')
        total -= sum(s.amount for s in self.savings if s.transaction_type == 'withdrawal')
        return total
    
    def total_loan_balance(self):
        total_borrowed = sum(l.amount for l in self.loans if l.status == 'active')
        total_repaid = sum(l.amount_repaid for l in self.loans if l.status == 'active')
        return total_borrowed - total_repaid

class Saving(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # deposit or withdrawal
    description = db.Column(db.String(200))
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)

class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    amount_repaid = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='active')  # active, completed, defaulted
    loan_date = db.Column(db.DateTime, default=datetime.utcnow)
    repayment_due_date = db.Column(db.DateTime)
    description = db.Column(db.String(200))
    
    def remaining_balance(self):
        return self.amount - self.amount_repaid

class ProxyCollection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    collector_name = db.Column(db.String(100), nullable=False)
    collector_phone = db.Column(db.String(20))
    collection_date = db.Column(db.DateTime, default=datetime.utcnow)
    collection_type = db.Column(db.String(20), nullable=False)  # loan or saving
    amount = db.Column(db.Float, nullable=False)
    reference_id = db.Column(db.Integer)
    relationship = db.Column(db.String(100))

class LoanPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50))  # cash, savings_deduction, proxy
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    proxy_collection_id = db.Column(db.Integer, db.ForeignKey('proxy_collection.id'))
    
    loan = db.relationship('Loan', backref='payments')
    proxy_collection = db.relationship('ProxyCollection', backref='loan_payment')

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    full_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        """Hash password using SHA-256"""
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    def check_password(self, password):
        """Verify password"""
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

# ============ DECORATORS ============
# Define decorators before using them in routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        admin = Admin.query.get(session['admin_id'])
        if admin.username != 'admin':  # Only master admin can access
            flash('Admin access required', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ============ TEMPLATE FILTERS ============
@app.template_filter('format_currency')
def format_currency(value):
    """Format currency with commas and Naira symbol"""
    if value is None:
        return "₦0.00"
    try:
        # Format with commas and 2 decimal places
        formatted = f"{value:,.2f}"
        return f"₦{formatted}"
    except (ValueError, TypeError):
        return f"₦{value}"

@app.template_filter('format_number')
def format_number(value):
    """Format number with commas (no decimal places)"""
    if value is None:
        return "0"
    try:
        return f"{value:,.0f}"
    except (ValueError, TypeError):
        return str(value)

@app.template_filter('format_decimal')
def format_decimal(value):
    """Format decimal with commas (no currency symbol)"""
    if value is None:
        return "0.00"
    try:
        return f"{value:,.2f}"
    except (ValueError, TypeError):
        return str(value)

# ============ CREATE TABLES AND DEFAULT ADMIN ============
with app.app_context():
    db.create_all()
    
    # Create default admin if not exists
    if not Admin.query.filter_by(username='admin').first():
        default_admin = Admin(username='admin', full_name='System Administrator')
        default_admin.set_password('admin123')  # Change this password!
        db.session.add(default_admin)
        db.session.commit()
        print("Default admin created - Username: admin, Password: admin123")

# ============ AUTHENTICATION ROUTES ============
@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to dashboard
    if 'admin_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            # Update last login
            admin.last_login = datetime.utcnow()
            db.session.commit()
            
            # Set session
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            session['admin_name'] = admin.full_name
            
            flash(f'Welcome back, {admin.full_name or admin.username}!', 'success')
            
            # Redirect to the page they were trying to access
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    admin = Admin.query.get(session['admin_id'])
    
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not admin.check_password(current_password):
            flash('Current password is incorrect', 'danger')
            return redirect(url_for('change_password'))
        
        if new_password != confirm_password:
            flash('New passwords do not match', 'danger')
            return redirect(url_for('change_password'))
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long', 'danger')
            return redirect(url_for('change_password'))
        
        admin.set_password(new_password)
        db.session.commit()
        
        flash('Password changed successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('change_password.html', admin=admin)

@app.route('/admin/users')
@admin_required
def manage_users():
    admins = Admin.query.all()
    return render_template('manage_users.html', admins=admins)

@app.route('/admin/add-user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        
        # Check if username exists
        if Admin.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('add_user'))
        
        new_admin = Admin(
            username=username,
            full_name=full_name,
            email=email
        )
        new_admin.set_password(password)
        db.session.add(new_admin)
        db.session.commit()
        
        flash(f'User {username} created successfully!', 'success')
        return redirect(url_for('manage_users'))
    
    return render_template('add_user.html')

@app.route('/admin/delete-user/<int:user_id>')
@admin_required
def delete_user(user_id):
    # Prevent deleting the main admin
    user = Admin.query.get_or_404(user_id)
    if user.username == 'admin':
        flash('Cannot delete the main admin user', 'danger')
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted successfully', 'success')
    
    return redirect(url_for('manage_users'))

# ============ CUSTOMER MANAGEMENT ROUTES ============
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '')
    if search:
        customers_list = Customer.query.filter(
            Customer.is_active == True,
            (Customer.name.contains(search)) | 
            (Customer.phone.contains(search))
        ).all()
    else:
        customers_list = Customer.query.filter_by(is_active=True).all()
    
    return render_template('customers.html', customers=customers_list, search=search)

@app.route('/customers/deleted')
@login_required
def deleted_customers():
    """View all soft-deleted customers"""
    search = request.args.get('search', '')
    if search:
        deleted_customers_list = Customer.query.filter(
            Customer.is_active == False,
            (Customer.name.contains(search)) | 
            (Customer.phone.contains(search))
        ).all()
    else:
        deleted_customers_list = Customer.query.filter_by(is_active=False).all()
    
    return render_template('deleted_customers.html', customers=deleted_customers_list, search=search)

@app.route('/customer/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        
        # Check if customer already exists
        existing = Customer.query.filter_by(phone=phone).first()
        if existing:
            flash('Customer with this phone number already exists!', 'danger')
            return redirect(url_for('add_customer'))
        
        customer = Customer(
            name=name,
            phone=phone,
            email=email,
            address=address
        )
        
        db.session.add(customer)
        db.session.commit()
        
        flash('Customer registered successfully!', 'success')
        return redirect(url_for('customers'))
    
    return render_template('add_customer.html')

@app.route('/customer/<int:customer_id>')
@login_required
def view_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    savings_history = customer.savings
    loans = Loan.query.filter_by(customer_id=customer_id, status='active').all()
    completed_loans = Loan.query.filter_by(customer_id=customer_id, status='completed').all()
    
    return render_template('view_customer.html', 
                         customer=customer, 
                         savings_history=savings_history,
                         loans=loans,
                         completed_loans=completed_loans)

@app.route('/customer/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'POST':
        customer.name = request.form.get('name')
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        
        db.session.commit()
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    return render_template('edit_customer.html', customer=customer)

@app.route('/customer/<int:customer_id>/delete', methods=['POST'])
@login_required
def delete_customer(customer_id):
    """Soft delete a customer (mark as inactive)"""
    customer = Customer.query.get_or_404(customer_id)
    
    # Check if customer has any active loans
    active_loans = Loan.query.filter_by(customer_id=customer_id, status='active').all()
    if active_loans:
        flash(f'Cannot delete {customer.name} because they have active loans. Please settle all loans first.', 'danger')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    # Soft delete - mark as inactive
    customer.is_active = False
    db.session.commit()
    
    flash(f'Customer {customer.name} has been deactivated successfully!', 'success')
    return redirect(url_for('customers'))

@app.route('/customer/<int:customer_id>/restore', methods=['POST'])
@login_required
def restore_customer(customer_id):
    """Restore a soft-deleted customer"""
    customer = Customer.query.get_or_404(customer_id)
    
    # Restore - mark as active
    customer.is_active = True
    db.session.commit()
    
    flash(f'Customer {customer.name} has been restored successfully!', 'success')
    return redirect(url_for('customers'))

@app.route('/customer/<int:customer_id>/permanent_delete', methods=['POST'])
@login_required
@admin_required
def permanent_delete_customer(customer_id):
    """Permanently delete a customer and all their data"""
    customer = Customer.query.get_or_404(customer_id)
    
    # Check if customer has any active loans
    active_loans = Loan.query.filter_by(customer_id=customer_id, status='active').all()
    if active_loans:
        flash(f'Cannot permanently delete {customer.name} because they have active loans.', 'danger')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    # Get customer name for flash message
    customer_name = customer.name
    
    # Permanently delete (all related records will be deleted due to cascade)
    db.session.delete(customer)
    db.session.commit()
    
    flash(f'Customer {customer_name} has been permanently deleted from the system!', 'warning')
    return redirect(url_for('customers'))

# ============ SAVINGS AND LOAN ROUTES ============
@app.route('/customer/<int:customer_id>/add_saving', methods=['POST'])
@login_required
def add_saving(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    amount = float(request.form.get('amount'))
    description = request.form.get('description', '')
    transaction_type = request.form.get('transaction_type')
    
    if transaction_type == 'withdrawal' and amount > customer.total_savings():
        flash('Insufficient savings balance!', 'danger')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    saving = Saving(
        customer_id=customer_id,
        amount=amount,
        transaction_type=transaction_type,
        description=description
    )
    
    db.session.add(saving)
    db.session.commit()
    
    flash(f'Saving {transaction_type} of ₦{amount:,.2f} recorded successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/add_loan', methods=['POST'])
@login_required
def add_loan(customer_id):
    amount = float(request.form.get('amount'))
    description = request.form.get('description', '')
    
    loan = Loan(
        customer_id=customer_id,
        amount=amount,
        description=description
    )
    
    db.session.add(loan)
    db.session.commit()
    
    flash(f'Loan of ₦{amount:,.2f} disbursed successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/repay_loan', methods=['POST'])
@login_required
def repay_loan(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    loan_id = int(request.form.get('loan_id'))
    amount = float(request.form.get('amount'))
    payment_method = request.form.get('payment_method')
    
    loan = Loan.query.get_or_404(loan_id)
    
    if payment_method == 'savings_deduction':
        if amount > customer.total_savings():
            flash('Insufficient savings to cover this payment!', 'danger')
            return redirect(url_for('view_customer', customer_id=customer_id))
        
        saving = Saving(
            customer_id=customer_id,
            amount=amount,
            transaction_type='withdrawal',
            description=f'Loan payment deduction for loan #{loan_id}'
        )
        db.session.add(saving)
    
    # Record loan payment
    payment = LoanPayment(
        loan_id=loan_id,
        amount=amount,
        payment_method=payment_method
    )
    db.session.add(payment)
    
    # Update loan repayment amount
    loan.amount_repaid += amount
    
    # Check if loan is fully repaid
    if loan.amount_repaid >= loan.amount:
        loan.status = 'completed'
        flash('Loan fully repaid! Congratulations!', 'success')
    
    db.session.commit()
    
    flash(f'Loan payment of ₦{amount:,.2f} recorded successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/proxy_collection', methods=['GET', 'POST'])
@login_required
def proxy_collection(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'POST':
        collector_name = request.form.get('collector_name')
        collector_phone = request.form.get('collector_phone')
        collection_type = request.form.get('collection_type')
        amount = float(request.form.get('amount'))
        relationship = request.form.get('relationship')
        loan_id = request.form.get('loan_id') if collection_type == 'loan' else None
        
        proxy = ProxyCollection(
            customer_id=customer_id,
            collector_name=collector_name,
            collector_phone=collector_phone,
            collection_type=collection_type,
            amount=amount,
            relationship=relationship
        )
        
        db.session.add(proxy)
        
        if collection_type == 'loan' and loan_id:
            loan = Loan.query.get(loan_id)
            if loan:
                # Record payment through proxy
                payment = LoanPayment(
                    loan_id=loan_id,
                    amount=amount,
                    payment_method='proxy',
                    proxy_collection_id=proxy.id
                )
                db.session.add(payment)
                loan.amount_repaid += amount
                
                if loan.amount_repaid >= loan.amount:
                    loan.status = 'completed'
        elif collection_type == 'saving':
            # Add to savings
            saving = Saving(
                customer_id=customer_id,
                amount=amount,
                transaction_type='deposit',
                description=f'Proxy collection by {collector_name}'
            )
            db.session.add(saving)
        
        db.session.commit()
        
        flash(f'Proxy collection recorded successfully! Amount: ₦{amount:,.2f}', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    active_loans = Loan.query.filter_by(customer_id=customer_id, status='active').all()
    return render_template('proxy_collection.html', customer=customer, active_loans=active_loans)

# ============ HISTORY ROUTES ============
@app.route('/proxy_history')
@login_required
def proxy_history():
    # Get filter parameters
    search_name = request.args.get('search_name', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    collection_type = request.args.get('collection_type', '')
    
    # Start with base query
    query = ProxyCollection.query
    
    # Apply filters
    if search_name:
        query = query.filter(
            (ProxyCollection.collector_name.contains(search_name)) |
            (ProxyCollection.customer.has(Customer.name.contains(search_name))) |
            (ProxyCollection.customer.has(Customer.phone.contains(search_name)))
        )
    
    if start_date:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(ProxyCollection.collection_date >= start_date_obj)
    
    if end_date:
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
        end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(ProxyCollection.collection_date <= end_date_obj)
    
    if collection_type:
        query = query.filter_by(collection_type=collection_type)
    
    # Order by most recent first
    proxy_collections = query.order_by(ProxyCollection.collection_date.desc()).all()
    
    # Get summary statistics
    total_amount = sum(p.amount for p in proxy_collections)
    loan_collections = sum(p.amount for p in proxy_collections if p.collection_type == 'loan')
    saving_collections = sum(p.amount for p in proxy_collections if p.collection_type == 'saving')
    
    return render_template('proxy_history.html',
                         proxy_collections=proxy_collections,
                         search_name=search_name,
                         start_date=start_date,
                         end_date=end_date,
                         collection_type=collection_type,
                         total_amount=total_amount,
                         loan_collections=loan_collections,
                         saving_collections=saving_collections)

@app.route('/savings_history')
@login_required
def savings_history():
    # Get filter parameters
    search_name = request.args.get('search_name', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    transaction_type = request.args.get('transaction_type', '')
    
    # Start with base query
    query = Saving.query
    
    # Apply filters
    if search_name:
        query = query.filter(Saving.customer.has(Customer.name.contains(search_name)))
    
    if start_date:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(Saving.transaction_date >= start_date_obj)
    
    if end_date:
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
        end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(Saving.transaction_date <= end_date_obj)
    
    if transaction_type:
        query = query.filter_by(transaction_type=transaction_type)
    
    # Order by most recent first
    savings = query.order_by(Saving.transaction_date.desc()).all()
    
    # Get summary statistics
    total_deposits = sum(s.amount for s in savings if s.transaction_type == 'deposit')
    total_withdrawals = sum(s.amount for s in savings if s.transaction_type == 'withdrawal')
    net_savings = total_deposits - total_withdrawals
    
    return render_template('savings_history.html',
                         savings=savings,
                         search_name=search_name,
                         start_date=start_date,
                         end_date=end_date,
                         transaction_type=transaction_type,
                         total_deposits=total_deposits,
                         total_withdrawals=total_withdrawals,
                         net_savings=net_savings)

@app.route('/proxy_collection/<int:proxy_id>')
@login_required
def view_proxy_details(proxy_id):
    proxy = ProxyCollection.query.get_or_404(proxy_id)
    return render_template('proxy_details.html', proxy=proxy)

@app.route('/reports')
@login_required
def reports():
    total_customers = Customer.query.filter_by(is_active=True).count()
    total_savings = sum(c.total_savings() for c in Customer.query.filter_by(is_active=True).all())
    total_loans_outstanding = sum(c.total_loan_balance() for c in Customer.query.filter_by(is_active=True).all())
    active_loans = Loan.query.filter_by(status='active').count()
    
    return render_template('reports.html',
                         total_customers=total_customers,
                         total_savings=total_savings,
                         total_loans_outstanding=total_loans_outstanding,
                         active_loans=active_loans)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))