# backend/utils/calculation.py

import logging
import traceback
import math
from backend.models import BankRate

def calculate_refinance_savings(original_loan_amount, original_loan_tenure, current_repayment):
    """
    Calculate potential refinance savings using the provided inputs.

    Parameters:
    - original_loan_amount (float): The original amount of the loan.
    - original_loan_tenure (int): The original loan tenure in years.
    - current_repayment (float): The current monthly repayment amount.

    Returns:
    - dict: A dictionary containing the savings details.
    """
    # Initialize default result
    result = {
        'monthly_savings': 0.0,
        'yearly_savings': 0.0,
        'lifetime_savings': 0.0,
        'new_monthly_repayment': 0.0,
        'years_saved': 0,
        'months_saved': 0,
        'new_interest_rate': 0.0,
        'bank_name': ''
    }

    try:
        # Enter function
        logging.debug("🚀 Entered calculate_refinance_savings()")
        logging.debug(f"Inputs - Loan Amount: {original_loan_amount}, Tenure: {original_loan_tenure}, Repayment: {current_repayment}")

        # 1️⃣ **Input Validation**
        if not original_loan_amount or not original_loan_tenure or not current_repayment:
            logging.error("❌ Missing essential input data. Cannot proceed with calculation.")
            return result  # Return default result with 0s

        # 2️⃣ **Query the Best Bank Rate**
        bank_rate = BankRate.query.filter(
            BankRate.min_amount <= original_loan_amount,
            BankRate.max_amount >= original_loan_amount
        ).order_by(BankRate.interest_rate).first()

        if bank_rate:
            result['new_interest_rate'] = bank_rate.interest_rate
            result['bank_name'] = bank_rate.bank_name
            logging.info(f"✅ Bank rate found: {bank_rate.interest_rate}% for bank: {bank_rate.bank_name}")
        else:
            logging.error(f"❌ No bank rate found for loan amount: {original_loan_amount}")
            return result  # Return default result with 0s

        # 3️⃣ **Calculate New Monthly Repayment**
        new_tenure_years = original_loan_tenure
        monthly_interest_rate = result['new_interest_rate'] / 100 / 12
        total_payments = new_tenure_years * 12

        if monthly_interest_rate == 0:
            new_monthly_repayment = original_loan_amount / total_payments
        else:
            new_monthly_repayment = original_loan_amount * (
                monthly_interest_rate * (1 + monthly_interest_rate) ** total_payments
            ) / ((1 + monthly_interest_rate) ** total_payments - 1)

        result['new_monthly_repayment'] = round(new_monthly_repayment, 2)
        logging.info(f"✅ New monthly repayment: {result['new_monthly_repayment']} RM")

        # 4️⃣ **Calculate Savings**
        monthly_savings = current_repayment - result['new_monthly_repayment']

        # ✅ **Calculate Yearly Savings**
        yearly_savings = monthly_savings * 12

        # ✅ **Calculate Lifetime Savings**
        existing_total_cost = current_repayment * original_loan_tenure * 12
        new_total_cost = result['new_monthly_repayment'] * original_loan_tenure * 12
        lifetime_savings = existing_total_cost - new_total_cost

        # ✅ **Store Savings in the Result**
        result['monthly_savings'] = round(monthly_savings, 2)
        result['yearly_savings'] = round(yearly_savings, 2)
        result['lifetime_savings'] = round(lifetime_savings, 2)
        logging.info(f"✅ Savings calculated. Monthly: {result['monthly_savings']} RM, Yearly: {result['yearly_savings']} RM, Lifetime: {result['lifetime_savings']} RM")

        # 5️⃣ **Calculate Years and Months Saved**
        if lifetime_savings > 0 and current_repayment > 0:
            total_months_saved = lifetime_savings / current_repayment
            logging.debug(f"Total months saved: {total_months_saved}")

            # Calculate years and months using math.floor and math.ceil
            years_saved = math.floor(total_months_saved / 12)
            remaining_months = total_months_saved % 12
            months_saved = math.ceil(remaining_months) if remaining_months > 0 else 0

            # Handle case where months_saved equals 12
            if months_saved == 12:
                years_saved += 1
                months_saved = 0

            # Ensure at least 1 month is saved if there are any savings
            if total_months_saved > 0 and months_saved == 0 and remaining_months > 0:
                months_saved = 1

            result['years_saved'] = years_saved
            result['months_saved'] = months_saved
            logging.info(f"✅ Years saved: {result['years_saved']} years, Months saved: {result['months_saved']} months")
        else:
            logging.info("✅ No savings applicable. Years and months saved remain 0.")

        return result

    except Exception as e:
        logging.error(f"❌ General error in refinance calculation: {e}")
        logging.error(f"Traceback: {traceback.format_exc()}")  # Optional for debugging
        return result  # Return default result with 0s
