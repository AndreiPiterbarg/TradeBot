import os
import time
from dotenv import load_dotenv
from coinbase.rest import RESTClient
import uuid
from requests.exceptions import HTTPError

MIN_PRICE_CHANGE_24_HRS = 6
TARGET_PERCENTAGE_PROFIT = 0.5
MAX_BALANCE_PERCENTAGE = 0.5  # Maximum percentage of total balance to spend

def main():
    load_dotenv()
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    rest_client = RESTClient(api_key=api_key, api_secret=api_secret)

    try:
        # Verify API credentials and list wallets
        wallets = rest_client.get_accounts()
        print("Available wallets:")
        for wallet in wallets['accounts']:
            print(f"Currency: {wallet['currency']}, ID: {wallet['uuid']}")

        # Get USDC wallet and verify balance
        wallet_id_usdc = os.getenv("USDC_WALLET_ID")
        usdc_wallet = rest_client.get_account(wallet_id_usdc)
        total_balance = float(usdc_wallet['account']['available_balance']['value'])
        print(f"USDC Wallet Balance: {total_balance} USDC")

        # Calculate maximum amount to spend
        max_spend = total_balance * MAX_BALANCE_PERCENTAGE
        print(f"Maximum amount to spend: {max_spend:.2f} USDC")

        # Get active sell orders
        active_orders = rest_client.list_orders(order_side="SELL", order_status=["OPEN"])
        products_being_sold = [order['product_id'] for order in active_orders['orders']]
        print(f"Currently selling: {', '.join(products_being_sold) or 'None'}")

        # Get potential products to buy
        spot_products = rest_client.get_products(product_type="SPOT")
        to_buy = [
            product for product in spot_products["products"]
            if (product['product_id'].endswith('USDC') and
                product['price_percentage_change_24h'] and
                float(product['price_percentage_change_24h']) > MIN_PRICE_CHANGE_24_HRS and
                product['product_id'] not in products_being_sold)
        ]
        print(f"Found {len(to_buy)} potential products to buy")

        # Calculate amount to spend on each product
        number_of_products_to_buy = len(to_buy)
        to_spend_on_each_product = min((max_spend / number_of_products_to_buy) * 0.98, max_spend)
        while to_spend_on_each_product <= 1 and number_of_products_to_buy > 0:
            number_of_products_to_buy -= 1
            to_spend_on_each_product = min((max_spend / number_of_products_to_buy) * 0.98, max_spend) if number_of_products_to_buy > 0 else 0

        if number_of_products_to_buy == 0:
            print("Not enough balance to buy any products")
            return

        print(f"Planning to buy {number_of_products_to_buy} products, spending {to_spend_on_each_product:.2f} USDC on each")

        # Execute buy orders and set sell orders
        for product in to_buy[:number_of_products_to_buy]:
            try:
                buy_order = execute_buy_order(rest_client, product, to_spend_on_each_product)
                if buy_order and buy_order.get('success', False):
                    print(f"Waiting an hour seconds before placing sell order for {product['product_id']}...")
                    time.sleep(5)  # Wait for 5 seconds to ensure the buy order is processed
                    execute_sell_order(rest_client, product)
                else:
                    print(f"Skipping sell order for {product['product_id']} due to failed buy order")
            except HTTPError as e:
                print(f"Error executing orders for {product['product_id']}: {e}")
            except Exception as e:
                print(f"Unexpected error for {product['product_id']}: {e}")

        print("Trading session completed")

    except HTTPError as e:
        print(f"Error accessing Coinbase API: {e}")
        print("Please check your API_KEY and API_SECRET in the .env file.")
    except Exception as e:
        print(f"Unexpected error: {e}")



def execute_buy_order(rest_client, product, quote_size):
    product_id = product['product_id']
    order_id = str(uuid.uuid4())
    
    # Round the quote size to 2 decimal places
    rounded_quote_size = round(quote_size, 2)
    print(f"Attempting to buy {rounded_quote_size:.2f} USDC of {product_id}")
    
    try:
        order = rest_client.market_order_buy(client_order_id=order_id, product_id=product_id, quote_size=str(rounded_quote_size))
        if order.get('success', False):
            order_id = order.get('success_response', {}).get('order_id') or 'Unknown'
            print(f"Buy order executed for {product_id}: {order_id}")
        else:
            print(f"Buy order failed for {product_id}")
        print(f"Order details: {order}")
        return order
    except HTTPError as e:
        print(f"Failed to execute buy order for {product_id}: {e}")
        return None

def execute_sell_order(rest_client, product):
    product_id = product['product_id']
    base_currency = product_id.split("-")[0]
    client_order_id = str(uuid.uuid4())

    try:
        # Get product information
        product_info = rest_client.get_product(product_id=product_id)
        min_base_size = float(product_info['base_min_size'])
        
        # Get wallet balance
        wallet = rest_client.get_account(base_currency)
        quantity_of_asset = float(wallet['account']['available_balance']['value'])
        
        # Get current market price
        ticker = rest_client.get_product_ticker(product_id=product_id)
        current_price = float(ticker['price'])
        
        limit_price = round(current_price * (1 + TARGET_PERCENTAGE_PROFIT), 6)

        if quantity_of_asset < min_base_size:
            print(f"Insufficient {base_currency} balance to sell. Current: {quantity_of_asset}, Minimum: {min_base_size}")
            return

        # Round the base size to 8 decimal places
        rounded_base_size = round(quantity_of_asset, 8)
        
        sell_order = rest_client.limit_order_gtc_sell(
            client_order_id=client_order_id,
            product_id=product_id,
            base_size=str(rounded_base_size),
            limit_price=str(limit_price)
        )
        if sell_order.get('success', False):
            sell_order_id = sell_order.get('success_response', {}).get('order_id') or 'Unknown'
            print(f"Sell order placed for {product_id}: {sell_order_id} at {limit_price}")
        else:
            print(f"Failed to place sell order for {product_id}")
        print(f"Sell order details: {sell_order}")
    except HTTPError as e:
        print(f"Failed to execute sell order for {product_id}: {e}")

if __name__ == "__main__":
    main()