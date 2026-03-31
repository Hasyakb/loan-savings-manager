from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

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
    transaction_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(200))
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)

class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    amount_repaid = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='active')
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
    collection_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference_id = db.Column(db.Integer)
    relationship = db.Column(db.String(100))

class LoanPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50))
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    proxy_collection_id = db.Column(db.Integer, db.ForeignKey('proxy_collection.id'))
    
    loan = db.relationship('Loan', backref='payments')
    proxy_collection = db.relationship('ProxyCollection', backref='loan_payment')

# Create tables
with app.app_context():
    db.create_all()

# Routes (keep all your existing routes here)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/customers')
def customers():
    search = request.args.get('search', '')
    if search:
        customers_list = Customer.query.filter(
            (Customer.name.contains(search)) | 
            (Customer.phone.contains(search))
        ).all()
    else:
        customers_list = Customer.query.all()
    
    return render_template('customers.html', customers=customers_list, search=search)

@app.route('/customer/add', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        
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

@app.route('/customer/<int:customer_id>/add_saving', methods=['POST'])
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
    
    flash(f'Saving {transaction_type} of ₦{amount:.2f} recorded successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/add_loan', methods=['POST'])
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
    
    flash(f'Loan of ₦{amount:.2f} disbursed successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/repay_loan', methods=['POST'])
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
    
    payment = LoanPayment(
        loan_id=loan_id,
        amount=amount,
        payment_method=payment_method
    )
    db.session.add(payment)
    
    loan.amount_repaid += amount
    
    if loan.amount_repaid >= loan.amount:
        loan.status = 'completed'
        flash('Loan fully repaid! Congratulations!', 'success')
    
    db.session.commit()
    
    flash(f'Loan payment of ₦{amount:.2f} recorded successfully!', 'success')
    return redirect(url_for('view_customer', customer_id=customer_id))

@app.route('/customer/<int:customer_id>/proxy_collection', methods=['GET', 'POST'])
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
            saving = Saving(
                customer_id=customer_id,
                amount=amount,
                transaction_type='deposit',
                description=f'Proxy collection by {collector_name}'
            )
            db.session.add(saving)
        
        db.session.commit()
        
        flash(f'Proxy collection recorded successfully! Amount: ₦{amount:.2f}', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    active_loans = Loan.query.filter_by(customer_id=customer_id, status='active').all()
    return render_template('proxy_collection.html', customer=customer, active_loans=active_loans)

@app.route('/proxy_history')
def proxy_history():
    search_name = request.args.get('search_name', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    collection_type = request.args.get('collection_type', '')
    
    query = ProxyCollection.query
    
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
    
    proxy_collections = query.order_by(ProxyCollection.collection_date.desc()).all()
    
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
def savings_history():
    search_name = request.args.get('search_name', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    transaction_type = request.args.get('transaction_type', '')
    
    query = Saving.query
    
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
    
    savings = query.order_by(Saving.transaction_date.desc()).all()
    
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
def view_proxy_details(proxy_id):
    proxy = ProxyCollection.query.get_or_404(proxy_id)
    return render_template('proxy_details.html', proxy=proxy)

@app.route('/reports')
def reports():
    total_customers = Customer.query.count()
    total_savings = sum(c.total_savings() for c in Customer.query.all())
    total_loans_outstanding = sum(c.total_loan_balance() for c in Customer.query.all())
    active_loans = Loan.query.filter_by(status='active').count()
    
    return render_template('reports.html',
                         total_customers=total_customers,
                         total_savings=total_savings,
                         total_loans_outstanding=total_loans_outstanding,
                         active_loans=active_loans)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))