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
        # Validate inputs
        if not original_loan_amount or not original_loan_tenure or not current_repayment:
            logging.error("❌ Missing essential input data. Cannot proceed with calculation.")
            return result

        # Query the best bank rate based on the original loan amount
        bank_rate = BankRate.query.filter(
            BankRate.min_amount <= original_loan_amount,
            BankRate.max_amount >= original_loan_amount
        ).order_by(BankRate.interest_rate).first()

        if bank_rate:
            result['new_interest_rate'] = bank_rate.interest_rate
            result['bank_name'] = bank_rate.bank_name
        else:
            logging.error(f"❌ No bank rate found for loan amount: {original_loan_amount}")
            return result

        # Calculate new monthly repayment
        monthly_interest_rate = result['new_interest_rate'] / 100 / 12
        total_payments = original_loan_tenure * 12

        if monthly_interest_rate == 0:
            new_monthly_repayment = original_loan_amount / total_payments
        else:
            new_monthly_repayment = original_loan_amount * (monthly_interest_rate * (1 + monthly_interest_rate) ** total_payments) / ((1 + monthly_interest_rate) ** total_payments - 1)

        result['new_monthly_repayment'] = round(new_monthly_repayment, 2)

        # Calculate savings
        monthly_savings = current_repayment - result['new_monthly_repayment']
        yearly_savings = monthly_savings * 12
        lifetime_savings = (current_repayment * original_loan_tenure * 12) - (result['new_monthly_repayment'] * original_loan_tenure * 12)

        result['monthly_savings'] = round(monthly_savings, 2)
        result['yearly_savings'] = round(yearly_savings, 2)
        result['lifetime_savings'] = round(lifetime_savings, 2)

        # Calculate years and months saved
        if lifetime_savings > 0 and current_repayment > 0:
            total_months_saved = lifetime_savings / current_repayment
            years_saved = total_months_saved // 12
            months_saved = total_months_saved % 12

            if months_saved == 12:  # Edge case where months_saved == 12
                years_saved += 1
                months_saved = 0

            result['years_saved'] = years_saved
            result['months_saved'] = months_saved

        return result

    except Exception as e:
        logging.error(f"❌ Error calculating refinance savings: {e}")
        return result  # Return the default result in case of error
