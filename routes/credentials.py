from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from services.websocket_service import leosac_client
from utils.rank_converter import USER_RANKS
from utils.permissions import has_permission

credentials_bp = Blueprint('credentials', __name__)

@credentials_bp.route('/credentials')
@login_required
def credentials_list():
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('credentials/list.html', credentials=[])
        credentials = leosac_client.get_credentials()
        return render_template('credentials/list.html', credentials=credentials)
    except Exception as e:
        flash(f'Error loading credentials: {str(e)}', 'error')
        return render_template('credentials/list.html', credentials=[])

@credentials_bp.route('/credentials/rfid/create', methods=['GET', 'POST'])
@login_required
def credentials_rfid_create():
    if not has_permission(getattr(current_user, 'rank', 'user'), 'credentials.create'):
        flash('You do not have permission to create credentials.', 'error')
        return redirect(url_for('credentials.credentials_list'))
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('credentials/rfid_create.html', credential_data=request.form, users=[])
            credential_data = {
                'alias': request.form.get('alias'),
                'card_id': request.form.get('card_id'),
                'nb_bits': request.form.get('nb_bits', 32),
                'description': request.form.get('description', ''),
                'owner': request.form.get('owner'),
                'validity_enabled': request.form.get('validity_enabled') == 'on'
            }
            if not all([credential_data['alias'], credential_data['card_id'], credential_data['nb_bits']]):
                flash('Alias, Card ID, and Number of Bits are required', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
            import re
            hex_regex = re.compile(r'^[0-9A-F]{2}(?::[0-9A-F]{2})*$', re.IGNORECASE)
            if not hex_regex.match(credential_data['card_id']):
                flash('Invalid card ID format. Use hex format like 00:22:28:c8 (hex pairs separated by colons)', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
            try:
                nb_bits = int(credential_data['nb_bits'])
                if nb_bits <= 0:
                    flash('Number of bits must be positive and divisible by 8', 'error')
                    return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
            except ValueError:
                flash('Number of bits must be a valid integer', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
            success, result = leosac_client.create_rfid_credential(credential_data)
            if success:
                flash('RFID credential created successfully!', 'success')
                return redirect(url_for('credentials.credentials_list'))
            else:
                error_msg = result.get('error', result.get('status_string', 'Unknown error')) if isinstance(result, dict) else str(result) if result else 'Unknown error'
                flash(f'Failed to create RFID credential: {error_msg}', 'error')
                return render_template('credentials/rfid_create.html', credential_data=credential_data, users=[])
        except Exception as e:
            flash(f'Error creating RFID credential: {str(e)}', 'error')
            return render_template('credentials/rfid_create.html', credential_data=request.form, users=[])
    try:
        users = leosac_client.get_users()
    except Exception as e:
        users = []
    return render_template('credentials/rfid_create.html', users=users)

@credentials_bp.route('/credentials/pin/create')
@login_required
def credentials_pin_create():
    return render_template('credentials/pin_create.html')

@credentials_bp.route('/credentials/<int:credential_id>')
@login_required
def credential_view(credential_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials.credentials_list'))
        credential = leosac_client.get_credential(credential_id)
        if credential:
            return render_template('credentials/view.html', credential=credential)
        else:
            flash('Credential not found', 'error')
            return redirect(url_for('credentials.credentials_list'))
    except Exception as e:
        flash(f'Error loading credential: {str(e)}', 'error')
        return redirect(url_for('credentials.credentials_list'))

@credentials_bp.route('/credentials/<int:credential_id>/edit', methods=['GET', 'POST'])
@login_required
def credential_edit(credential_id):
    if not has_permission(getattr(current_user, 'rank', 'user'), 'credentials.update'):
        flash('You do not have permission to edit credentials.', 'error')
        return redirect(url_for('credentials.credentials_list'))
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials.credential_view', credential_id=credential_id))
        credential = leosac_client.get_credential(credential_id)
        if not credential:
            flash('Credential not found', 'error')
            return redirect(url_for('credentials.credentials_list'))
        if request.method == 'POST':
            credential_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'owner': request.form.get('owner'),
                'validity_enabled': request.form.get('validity_enabled') == 'on'
            }
            if credential['type'] == 'rfid-card':
                credential_data.update({
                    'card_id': request.form.get('card_id'),
                    'nb_bits': request.form.get('nb_bits', 32)
                })
            if not credential_data['alias']:
                flash('Alias is required', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])
            if credential['type'] == 'rfid-card':
                import re
                hex_regex = re.compile(r'^[0-9A-F]{2}(?::[0-9A-F]{2})*$', re.IGNORECASE)
                if not hex_regex.match(credential_data['card_id']):
                    flash('Invalid card ID format. Use hex format like aa:bb:cc:11 (hex pairs separated by colons)', 'error')
                    return render_template('credentials/edit.html', credential=credential, users=[])
            if credential['type'] == 'rfid-card':
                success, result = leosac_client.update_rfid_credential(credential_id, credential_data)
            else:
                flash('PIN code editing not yet implemented', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])
            if success:
                flash('Credential updated successfully!', 'success')
                return redirect(url_for('credentials.credential_view', credential_id=credential_id))
            else:
                error_msg = result.get('error', result.get('status_string', 'Unknown error')) if isinstance(result, dict) else str(result) if result else 'Unknown error'
                flash(f'Failed to update credential: {error_msg}', 'error')
                return render_template('credentials/edit.html', credential=credential, users=[])
        try:
            users = leosac_client.get_users()
        except Exception as e:
            users = []
        return render_template('credentials/edit.html', credential=credential, users=users)
    except Exception as e:
        flash(f'Error editing credential: {str(e)}', 'error')
        return redirect(url_for('credentials.credential_view', credential_id=credential_id))

@credentials_bp.route('/credentials/<int:credential_id>/disable', methods=['POST'])
@login_required
def credential_disable(credential_id):
    if not has_permission(getattr(current_user, 'rank', 'user'), 'credentials.update'):
        flash('You do not have permission to disable credentials.', 'error')
        return redirect(url_for('credentials.credentials_list'))
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials.credentials_list'))
        success, result = leosac_client.disable_credential(credential_id)
        if success:
            flash('Credential disabled successfully!', 'success')
        else:
            error_msg = result.get('error', result.get('status_string', 'Unknown error')) if isinstance(result, dict) else str(result) if result else 'Unknown error'
            flash(f'Failed to disable credential: {error_msg}', 'error')
    except Exception as e:
        flash(f'Error disabling credential: {str(e)}', 'error')
    return redirect(url_for('credentials.credentials_list'))

@credentials_bp.route('/credentials/<int:credential_id>/enable', methods=['POST'])
@login_required
def credential_enable(credential_id):
    if not has_permission(getattr(current_user, 'rank', 'user'), 'credentials.update'):
        flash('You do not have permission to enable credentials.', 'error')
        return redirect(url_for('credentials.credentials_list'))
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('credentials.credentials_list'))
        success, result = leosac_client.enable_credential(credential_id)
        if success:
            flash('Credential enabled successfully!', 'success')
        else:
            error_msg = result.get('error', result.get('status_string', 'Unknown error')) if isinstance(result, dict) else str(result) if result else 'Unknown error'
            flash(f'Failed to enable credential: {error_msg}', 'error')
    except Exception as e:
        flash(f'Error enabling credential: {str(e)}', 'error')
    return redirect(url_for('credentials.credentials_list')) 