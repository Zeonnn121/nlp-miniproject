Terminal 1 — Backend (from the project root,  NetWatch/ ):

// bash
cd backend
source env/Scripts/activate
python manage.py runserver

→ http://127.0.0.1:8000/api/health/

Terminal 2 — Frontend (project root again):

// bash
cd frontend
npm run dev

→ http://localhost:5173

admin@example.com
zeondsouza

Create Offline Demo with IP 192.0.2.123.
Click Run check twice without changing anything.
It should remain Offline with one active fault.
Change the same device to 127.0.0.1.
Click Run check.
Only then should the old fault become Resolved.

************************************************
Run the app

Terminal 1 — backend

// bash
cd backend
env/Scripts/python manage.py migrate --noinput   # first time / after pulling changes
env/Scripts/python manage.py runserver

→ http://127.0.0.1:8000/api/health/

Terminal 2 — frontend

// bash
cd frontend
npm run dev

→ http://localhost:5173 (login:  admin@example.com  /  zeondsouza )

Optional — background monitoring (needed for automatic periodic checks; "Run monitoring check" buttons work without it)

// bash
redis-server                                      # separate terminal
cd backend
env/Scripts/python -m celery -A backend worker -l info
env/Scripts/python -m celery -A backend beat -l info

Verify changes

// bash
# Backend
cd backend
env/Scripts/python manage.py check
env/Scripts/python manage.py makemigrations --check --dry-run
env/Scripts/python manage.py test
 
# Frontend
cd frontend
npm run lint
npm run build

Try the new HTTP endpoint feature

1. Open a device → Device details
2. Scroll to Endpoint monitoring, tick Probe this endpoint, set URL (e.g.  http://127.0.0.1:8000/api/health/ ), Save endpoint settings
3. Click Run monitoring check
4. You should see the Endpoint status card go green with  HTTP 200 , and an HTTP response time trend chart appear
5. To see a fault: change the URL to  http://127.0.0.1:9/ , run check again →  HTTP_ENDPOINT_FAILURE  (critical) on the Faults page; change it back, run check → resolves

> Note: the first  runserver  after these changes needs the  migrate  step — I already ran it against your local  db.sqlite3 , so you're set unless you re-clone.


Two things worth knowing:  manage.py test  takes ~2 minutes (152 tests), and  check --deploy  will show 5 warnings locally — that's expected in dev, per the README.