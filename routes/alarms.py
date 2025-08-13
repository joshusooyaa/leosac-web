from flask import Blueprint, render_template
from flask_login import login_required

alarms_bp = Blueprint('alarms', __name__)

@alarms_bp.route('/alarms')
@login_required
def alarms_page():
    return render_template('alarms/list.html')


