# My API App

This project is a FastAPI application that serves personalized recommendations from the saved local recommender artifact.

## Project Structure

```
my-api-app
├── app
│   ├── __init__.py
│   ├── main.py
│   ├── ui.py
│   └── api
│       ├── __init__.py
│       └── recommendations.py
├── scripts
│   └── generate_synthetic_data.py
├── tests
│   └── test_recommendations.py
├── requirements.txt
└── README.md
```

## Setup Instructions

1. **Clone the repository:**

   ```
   git clone <repository-url>
   cd my-api-app
   ```

2. **Create a virtual environment:**

   ```
   python -m venv venv
   ```

3. **Activate the virtual environment:**
   - On Windows:
     ```
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```
     source venv/bin/activate
     ```

4. **Install the required dependencies:**
   ```
   pip install -r requirements.txt
   ```

## Usage

To run the FastAPI application, execute the following command:

```
uvicorn app.main:app --reload
```

You can access the API documentation at `http://127.0.0.1:8000/docs`.

You can also use the browser UI at `http://127.0.0.1:8000/` or `http://127.0.0.1:8000/ui`.

### Endpoints

- `GET /health`
- `GET /`
- `GET /ui`
- `GET /recommendations?customer_id=<id>&top_n=5`
- `GET /recommendations/{customer_id}?top_n=5`

The API reads the saved model from `../models/final_model.joblib` and uses the embedded customer and product tables from that artifact.

The browser UI lets you pick a known customer ID from the model, choose `top_n`, and fetch recommendations directly in the page.

## Testing

To run the tests, ensure your virtual environment is activated and execute:

```
pytest tests/test_recommendations.py
```

## License

This project is licensed under the MIT License.
