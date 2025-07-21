from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from services.websocket_service import leosac_client
import re
import logging
logger = logging.getLogger(__name__)
import traceback

schedules_bp = Blueprint('schedules', __name__)

def pad_time(timestr):
    # Accepts '0:0', '6:0', '12:59', etc. Returns '00:00', '06:00', '12:59'
    if not timestr:
        return ''
    parts = str(timestr).split(':')
    if len(parts) == 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return timestr

def group_timeframes_for_display(timeframes):
    if not timeframes:
        return []
    grouped = {}
    for tf in timeframes:
        start_time = pad_time(tf.get('start-time') or tf.get('start_time'))
        end_time = pad_time(tf.get('end-time') or tf.get('end_time'))
        day = tf.get('day')
        if start_time and end_time and day is not None:
            key = f"{start_time}-{end_time}"
            if key not in grouped:
                grouped[key] = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'days': set()
                }
            grouped[key]['days'].add(int(day))
    result = []
    for i, (key, data) in enumerate(grouped.items()):
        timeframe = {
            'id': i,
            'start_time': data['start_time'],
            'end_time': data['end_time'],
            'days': sorted(list(data['days']))
        }
        result.append(timeframe)
    return result

@schedules_bp.route('/schedules')
@login_required
def schedules_list():
    try:
        logger.info('--- schedules_list called ---')
        auth_state = leosac_client.get_auth_state()
        logger.info(f'Auth state: {auth_state}')
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in schedules_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('index'))
        schedules = leosac_client.get_schedules()
        logger.info(f'Schedules returned: {schedules}')
        return render_template('schedules/list.html', schedules=schedules)
    except Exception as e:
        logger.error(f'Error loading schedules: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash('Error loading schedules. Please try again.', 'error')
        return redirect(url_for('index'))

@schedules_bp.route('/schedules/create', methods=['GET', 'POST'])
@login_required
def schedules_create():
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('schedules.schedules_list'))
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/create.html')
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/create.html')
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/create.html')
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/create.html')
            timeframes = []
            timeframe_counter = 0
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                if start_time and end_time:
                    selected_days = []
                    for day_name, day_value in [
                        ('monday', 0), ('tuesday', 1), ('wednesday', 2), 
                        ('thursday', 3), ('friday', 4), ('saturday', 5), ('sunday', 6)
                    ]:
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,
                            'end-time': end_time,
                            'day': day
                        }
                        timeframes.append(timeframe)
                timeframe_counter += 1
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }
            success, result = leosac_client.create_schedule(schedule_data)
            if success:
                flash('Schedule created successfully!', 'success')
                return redirect(url_for('schedules.schedule_view', schedule_id=result['id']))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to create schedule: {error_msg}', 'error')
                return render_template('schedules/create.html')
        except Exception as e:
            flash('Error creating schedule. Please try again.', 'error')
            return render_template('schedules/create.html')
    return render_template('schedules/create.html')

@schedules_bp.route('/schedules/<int:schedule_id>')
@login_required
def schedule_view(schedule_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        schedule = leosac_client.get_schedule(schedule_id)
        if schedule:
            if schedule.get('timeframes'):
                schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])
            return render_template('schedules/view.html', schedule=schedule)
        else:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules.schedules_list'))
    except Exception as e:
        flash('Error loading schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list'))

@schedules_bp.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def schedule_edit(schedule_id):
    try:
        logger.info(f'--- schedule_edit called for schedule_id={schedule_id} ---')
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        schedule = leosac_client.get_schedule(schedule_id)
        logger.info(f'Raw schedule from API: {schedule}')
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        users = leosac_client.get_users()
        groups = leosac_client.get_groups()
        credentials = leosac_client.get_credentials()
        doors = leosac_client.get_doors()
        if schedule.get('timeframes'):
            logger.info(f'Original timeframes: {schedule["timeframes"]}')
            schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])
            logger.info(f'Processed timeframes: {schedule["timeframes"]}')
        if request.method == 'POST':
            logger.info(f'Processing POST request for schedule {schedule_id}')
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            logger.info(f'Form data - name: {name}, description: {description}')
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            timeframes = []
            timeframe_counter = 0
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                logger.info(f'Processing timeframe {timeframe_counter}: start_time={start_time}, end_time={end_time}')
                if start_time and end_time:
                    selected_days = []
                    for day_name, day_value in [
                        ('monday', 0), ('tuesday', 1), ('wednesday', 2), 
                        ('thursday', 3), ('friday', 4), ('saturday', 5), ('sunday', 6)
                    ]:
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                    logger.info(f'Selected days for timeframe {timeframe_counter}: {selected_days}')
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,
                            'end-time': end_time,
                            'day': day
                        }
                        timeframes.append(timeframe)
                timeframe_counter += 1
            logger.info(f'Processed timeframes: {timeframes}')
            mapping_data = []
            mapping_indices = set()
            import re as _re
            for key in request.form.keys():
                if key.startswith('mappings['):
                    m = _re.match(r'mappings\[(\d+)\]', key)
                    if m:
                        mapping_indices.add(int(m.group(1)))
            logger.info(f'Found mapping indices: {mapping_indices}')
            all_users = []
            all_groups = []
            all_credentials = []
            all_doors = []
            alias = None
            for idx in sorted(mapping_indices):
                this_alias = request.form.get(f'mappings[{idx}][alias]', '').strip()
                if this_alias and not alias:
                    alias = this_alias
                users_selected = request.form.getlist(f'mappings[{idx}][users][]')
                groups_selected = request.form.getlist(f'mappings[{idx}][groups][]')
                credentials_selected = request.form.getlist(f'mappings[{idx}][credentials][]')
                doors_selected = request.form.getlist(f'mappings[{idx}][doors][]')
                logger.info(f'Mapping {idx}: alias={this_alias}, users={users_selected}, groups={groups_selected}, credentials={credentials_selected}, doors={doors_selected}')
                all_users.extend([int(uid) for uid in users_selected if uid and uid.strip()])
                all_groups.extend([int(gid) for gid in groups_selected if gid and gid.strip()])
                all_credentials.extend([int(cid) for cid in credentials_selected if cid and cid.strip()])
                all_doors.extend([int(did) for did in doors_selected if did and did.strip()])
            all_users = list(set(all_users))
            all_groups = list(set(all_groups))
            all_credentials = list(set(all_credentials))
            all_doors = list(set(all_doors))
            mapping_data = []
            if alias and (all_users or all_groups or all_credentials or all_doors):
                mapping = {
                    'alias': alias,
                    'users': all_users,
                    'groups': all_groups,
                    'credentials': all_credentials,
                    'doors': all_doors,
                    'zones': []
                }
                mapping_data.append(mapping)
            logger.info(f'Final mapping data: {mapping_data}')
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }
            logger.info(f'Final schedule data: {schedule_data}')
            success, result = leosac_client.update_schedule(schedule_id, schedule_data, mapping_data)
            logger.info(f'Update result: success={success}, result={result}')
            if success:
                flash('Schedule updated successfully!', 'success')
                return redirect(url_for('schedules.schedule_view', schedule_id=schedule_id))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to update schedule: {error_msg}', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
        return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
    except Exception as e:
        logger.error(f'Error editing schedule {schedule_id}: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash('Error editing schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list'))

@schedules_bp.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
def schedule_delete(schedule_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        success, result = leosac_client.delete_schedule(schedule_id)
        if success:
            flash('Schedule deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error occurred')
            flash(f'Failed to delete schedule: {error_msg}', 'error')
        return redirect(url_for('schedules.schedules_list'))
    except Exception as e:
        flash('Error deleting schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list')) 