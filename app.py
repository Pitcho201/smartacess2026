import sqlite3
from flask import Flask, render_template, redirect, url_for, request, session, send_from_directory, jsonify, abort, send_file, Response, flash, get_flashed_messages
from werkzeug.security import check_password_hash, generate_password_hash
import face_recognition
import numpy as np
import mediapipe as mp
from liveness_utils import verificar_liveness_face_mesh
import base64
import cv2
import os
import csv
import io
from export_utils import exportar_pdf
from datetime import datetime
from werkzeug.utils import secure_filename
from stats_utils import get_monthly_attendance_stats
import logging
from facial_utils import identificar_rosto, carregar_rostos_conhecidos_incremental, salvar_cache, carregar_cache, identificar_multiplos_rostos, buscar_dados_estudante, buscar_dados_funcionario

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
# Inicialização da aplicação Flask
app = Flask(__name__)
app.secret_key = '945718730Jpn'

# Configuração de logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Variáveis globais para os rostos conhecidos
known_face_encodings, known_face_names, known_face_data, known_face_estruturas = carregar_cache()
if not known_face_encodings:
    known_face_encodings, known_face_names, known_face_data, known_face_estruturas = carregar_rostos_conhecidos_incremental()
    salvar_cache(known_face_encodings, known_face_names,
                 known_face_data, known_face_estruturas)

# Lista de administradores autorizados
ADMINISTRADORES = ['admin']

# Rota para servir arquivos da pasta 'known_faces'


@app.route('/known_faces/<filename>')
def known_faces(filename):
    # CRÍTICO: Permite que qualquer utilizador logado aceda às imagens.
    # O risco de segurança é mitigado porque a rota é chamada apenas pelo JS
    # após um reconhecimento bem-sucedido.
    if 'usuario' not in session:
        abort(403)  # Não logado

    caminho = os.path.join('known_faces', filename)
    if not os.path.exists(caminho):
        # A imagem pode ter uma extensão diferente ou não existir,
        # mas o abort(404) é correto.
        abort(404)

    return send_from_directory('known_faces', filename)

# Função para conectar ao banco de dados SQLite


def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Rota principal (index)


@app.route('/')
def index():
    return render_template('index.html')

# Rota de login


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        senha = request.form['senha']

        conn = get_db_connection()

        # 1. Tentar login como ADMINISTRADOR (Geral)
        admin = conn.execute(
            'SELECT * FROM administradores WHERE usuario = ?', (usuario,)).fetchone()

        if admin:
            if check_password_hash(admin['senha'], senha):
                session['usuario'] = usuario
                session['tipo_usuario'] = 'Admin'  # Tipo: Admin Geral
                session['entidade_id'] = admin['id']
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                flash('Senha inválida.', 'danger')
                conn.close()
                # Adicionado redirect para evitar execução desnecessária
                return redirect(url_for('login'))

        # 2. Tentar login como ADMINISTRADOR DE FUNCIONÁRIOS
        admin_funcional = conn.execute(
            'SELECT * FROM administradores_funcional WHERE usuario = ?', (usuario,)).fetchone()

        if admin_funcional:
            if check_password_hash(admin_funcional['senha_hash'], senha):
                session['usuario'] = usuario
                session['tipo_usuario'] = 'Funcionario_Admin'  # NOVO TIPO
                session['entidade_id'] = admin_funcional['id']
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                flash('Senha inválida.', 'danger')
                conn.close()
                return redirect(url_for('login'))  # Adicionado redirect

        # 3. Tentar login como PROFESSOR
        professor_cred = conn.execute(
            '''SELECT cp.usuario, cp.senha_hash, cp.professor_id, p.nome 
               FROM credenciais_professores cp 
               INNER JOIN professores p ON cp.professor_id = p.id 
               WHERE cp.usuario = ?''', (usuario,)).fetchone()

        if professor_cred:
            if check_password_hash(professor_cred['senha_hash'], senha):
                session['usuario'] = usuario
                session['tipo_usuario'] = 'Professor'
                session['entidade_id'] = professor_cred['professor_id']
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                flash('Senha inválida.', 'danger')
                conn.close()
                return redirect(url_for('login'))  # Adicionado redirect

        # [NOVO] 4. Tentar login como FUNCIONÁRIO (Acesso Restrito ao Ponto/Seus Registros)
        funcionario_cred = conn.execute(
            '''SELECT cf.usuario, cf.senha_hash, cf.funcionario_id, f.nome 
               FROM credenciais_funcionarios cf 
               INNER JOIN funcionarios f ON cf.funcionario_id = f.id 
               WHERE cf.usuario = ?''', (usuario,)).fetchone()  # <-- Assume nova tabela credenciais_funcionarios

        if funcionario_cred:
            if check_password_hash(funcionario_cred['senha_hash'], senha):
                session['usuario'] = usuario
                session['tipo_usuario'] = 'Funcionario'  # NOVO TIPO
                session['entidade_id'] = funcionario_cred['funcionario_id']
                conn.close()
                return redirect(url_for('dashboard'))
            else:
                flash('Senha inválida.', 'danger')
                conn.close()
                return redirect(url_for('login'))  # Adicionado redirect

        # Se não for encontrado em nenhuma das quatro tabelas/tipos
        flash('Usuário ou Senha inválida.', 'danger')
        conn.close()

    return render_template('login.html', messages=get_flashed_messages(with_categories=True))

# Rota de logout


@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('index'))


# ==============================================================================
# FUNÇÕES DE SUPORTE PARA O DASHBOARD (Funcionários)
# ==============================================================================

def get_employee_filters(conn):
    """Busca Funções e Departamentos únicos para os filtros do dashboard."""
    cursor = conn.cursor()
    # DISTINCT Funções
    funcoes = cursor.execute(
        "SELECT DISTINCT funcao FROM funcionarios WHERE funcao IS NOT NULL AND funcao != '' ORDER BY funcao").fetchall()
    # DISTINCT Departamentos
    departamentos = cursor.execute(
        "SELECT DISTINCT departamento FROM funcionarios WHERE departamento IS NOT NULL AND departamento != '' ORDER BY departamento").fetchall()
    return funcoes, departamentos


def get_employee_records(conn, termo, data_inicio, data_fim, funcao_filtro, departamento_filtro):
    """Busca registros de ponto dos funcionários com filtros aplicados."""
    sql = '''
        SELECT 
            rf.id, rf.data_hora, rf.tipo_registo, 
            f.nome, f.numero_bi, f.funcao, f.departamento
        FROM registo_funcionarios rf
        INNER JOIN funcionarios f ON rf.funcionario_id = f.id
        WHERE 1=1
    '''
    params = []

    if termo:
        sql += ' AND (f.nome LIKE ? OR f.numero_bi LIKE ?)'
        params += [f'%{termo}%', f'%{termo}%']

    if funcao_filtro:
        sql += ' AND f.funcao = ?'
        params.append(funcao_filtro)

    if departamento_filtro:
        sql += ' AND f.departamento = ?'
        params.append(departamento_filtro)

    if data_inicio:
        sql += ' AND date(rf.data_hora) >= date(?)'
        params.append(data_inicio)

    if data_fim:
        sql += ' AND date(rf.data_hora) <= date(?)'
        params.append(data_fim)

    sql += ' ORDER BY rf.data_hora DESC'

    cursor = conn.cursor()
    cursor.execute(sql, tuple(params))
    return cursor.fetchall()

# ----------------------------------------------------------------------
# DASHBOARD PRINCIPAL (Lógica de Módulo)
# ----------------------------------------------------------------------


@app.route('/dashboard/', defaults={'curso_param': 'Todos'})
@app.route('/dashboard/<curso_param>')
def dashboard(curso_param):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # RECUPERA INFORMAÇÕES DA SESSÃO
    tipo_usuario = session.get('tipo_usuario')
    entidade_id = session.get('entidade_id')

    # Inicialização do curso principal para o template
    curso_principal_prof = None

    conn = get_db_connection()

    # [CORREÇÃO 1: CARREGAMENTO DE DADOS INICIAIS DO PROFESSOR]
    if tipo_usuario == 'Professor':
        # Consulta para obter TODOS os cursos associados ao professor (para o filtro e nome principal)
        cursos_associados_query = conn.execute('''
            SELECT curso FROM professor_curso WHERE professor_id = ?
        ''', (entidade_id,)).fetchall()

        cursos_associados_prof = [c['curso'] for c in cursos_associados_query]

        # Define o curso principal (usado no input hidden do template)
        if cursos_associados_prof:
            curso_principal_prof = cursos_associados_prof[0]
        else:
            curso_principal_prof = 'Nenhum'

    # NOVO FILTRO: MÓDULO (Valor padrão é 'estudantes')
    modulo_filtro = request.args.get('modulo', 'estudantes')

    if tipo_usuario == 'Professor':
        modulo_filtro = 'estudantes'

    if tipo_usuario in ['Funcionario_Admin', 'Funcionario']:
        modulo_filtro = 'funcionarios'

    registros = []

    # Filtros de data e termo são comuns a ambos os módulos
    termo = request.args.get('termo', '').strip()
    data_inicio = request.args.get('data_inicio', '').strip()
    data_fim = request.args.get('data_fim', '').strip()

    # Inicialização de filtros específicos
    curso_filtro = request.args.get(
        'curso', curso_param)  # Lê o curso do request/URL
    disciplina_filtro = request.args.get('disciplina', '').strip()
    professor_filtro = request.args.get('professor', '').strip()

    disciplinas = []
    professores = []
    funcoes_disponiveis = []
    departamentos_disponiveis = []
    funcao_filtro = request.args.get('funcao', '').strip()
    departamento_filtro = request.args.get('departamento', '').strip()

    cursos_disponiveis = []

    # ===============================================
    # LÓGICA DO MÓDULO ESTUDANTES
    # ===============================================
    if modulo_filtro == 'estudantes':

        sql = '''
            SELECT 
                e.id, e.data_hora, s.nome, s.numero_bi, s.curso,
                d.nome AS nome_disciplina,
                p.nome AS nome_professor
            FROM entradas e
            INNER JOIN estudantes s ON e.estudante_id = s.id
            LEFT JOIN disciplinas d ON e.disciplina_id = d.id
            LEFT JOIN professores p ON e.professor_id = p.id
            WHERE 1=1
        '''
        params = []

        # --------------------------------------------------------------------
        # RESTRIÇÃO DOMINANTE PARA O PROFESSOR
        # --------------------------------------------------------------------
        if tipo_usuario == 'Professor':

            # [CORREÇÃO 2]: Garante que as listas de filtros do Professor sejam preenchidas
            cursos_disponiveis = cursos_associados_prof  # Da consulta feita no início

            # Carrega disciplinas do professor (para o dropdown)
            ofertas_prof = conn.execute('''
               SELECT DISTINCT d.id AS disciplina_id, d.nome AS disciplina_nome
               FROM professor_oferta po
               INNER JOIN oferta_disciplina od ON po.oferta_id = od.id 
               INNER JOIN disciplinas d ON od.disciplina_id = d.id
               WHERE po.professor_id = ? ORDER BY d.nome
            ''', (entidade_id,)).fetchall()
            disciplinas = [{'id': o['disciplina_id'],
                            'nome': o['disciplina_nome']} for o in ofertas_prof]

            # Carrega o próprio professor para o dropdown do professor
            professores = conn.execute(
                'SELECT id, nome FROM professores WHERE id = ?', (entidade_id,)).fetchall()

            # Restrição a) Restringe pelo ID do professor (Obrigatório)
            sql += ' AND e.professor_id = ?'
            params.append(entidade_id)
            # Força o filtro dele na interface
            professor_filtro = str(entidade_id)

            # Restrição b/c) Aplica o filtro de curso ou a lista completa de cursos associados
            if curso_filtro and curso_filtro != 'Todos':
                if curso_filtro in cursos_associados_prof:
                    sql += ' AND s.curso = ?'
                    params.append(curso_filtro)
                else:
                    sql += ' AND 1=0'  # Garante 0 resultados

            elif cursos_associados_prof:
                # Se 'Todos' e tiver cursos, aplica a restrição de cursos associados
                placeholders = ','.join(['?'] * len(cursos_associados_prof))
                sql += f' AND s.curso IN ({placeholders})'
                params.extend(cursos_associados_prof)

        # --------------------------------------------------------------------
        # FILTROS GERAIS PARA ADMINISTRADOR (Admin/Outros)
        # --------------------------------------------------------------------
        else:
            if curso_filtro and curso_filtro != 'Todos':
                sql += ' AND s.curso = ?'
                params.append(curso_filtro)

            if disciplina_filtro:
                sql += ' AND d.id = ?'
                params.append(disciplina_filtro)

            if professor_filtro:
                sql += ' AND p.id = ?'
                params.append(professor_filtro)

            # Popula filtros de Admin
            disciplinas = conn.execute(
                'SELECT id, nome FROM disciplinas ORDER BY nome').fetchall()
            professores = conn.execute(
                'SELECT id, nome FROM professores ORDER BY nome').fetchall()
            cursos_disponiveis = [c['curso'] for c in conn.execute(
                'SELECT DISTINCT curso FROM estudantes WHERE curso IS NOT NULL ORDER BY curso').fetchall()]

        # --------------------------------------------------------------------
        # FILTROS COMUNS (Termo e Data)
        # --------------------------------------------------------------------
        if termo:
            sql += ' AND (s.nome LIKE ? OR s.numero_bi LIKE ?)'
            params += [f'%{termo}%', f'%{termo}%']
        if data_inicio:
            sql += ' AND date(e.data_hora) >= date(?)'
            params.append(data_inicio)
        if data_fim:
            sql += ' AND date(e.data_hora) <= date(?)'
            params.append(data_fim)

        sql += ' ORDER BY e.data_hora DESC'
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        registros = cursor.fetchall()

    # ===============================================
    # LÓGICA DO MÓDULO FUNCIONÁRIOS
    # ===============================================
    elif modulo_filtro == 'funcionarios':

        # ... (A lógica do módulo Funcionários é mantida inalterada) ...
        if tipo_usuario in ['Admin', 'Funcionario_Admin', 'Funcionario']:

            funcionario_id_filtro = None
            if tipo_usuario == 'Funcionario':
                funcionario_id_filtro = entidade_id

            # Condição para aplicar filtros administrativos (apenas Admin/Funcionario_Admin)
            if tipo_usuario == 'Admin' or tipo_usuario == 'Funcionario_Admin':
                funcao_filtro = request.args.get('funcao', '').strip()
                departamento_filtro = request.args.get(
                    'departamento', '').strip()
            else:
                funcao_filtro = ''
                departamento_filtro = ''

            # --- LÓGICA DE BUSCA DO REGISTRO DE FUNCIONÁRIOS ---
            sql_func = '''
                 SELECT r.id, r.data_hora, r.tipo_registo, f.nome, f.numero_bi, f.funcao, f.departamento
                 FROM registo_funcionarios r
                 INNER JOIN funcionarios f ON r.funcionario_id = f.id
                 WHERE 1=1
             '''
            params_func = []

            if funcionario_id_filtro:
                sql_func += ' AND r.funcionario_id = ?'
                params_func.append(funcionario_id_filtro)

            if funcao_filtro:
                sql_func += ' AND f.funcao = ?'
                params_func.append(funcao_filtro)
            if departamento_filtro:
                sql_func += ' AND f.departamento = ?'
                params_func.append(departamento_filtro)
            if termo:
                sql_func += ' AND (f.nome LIKE ? OR f.numero_bi LIKE ?)'
                params_func += [f'%{termo}%', f'%{termo}%']
            if data_inicio:
                sql_func += ' AND date(r.data_hora) >= date(?)'
                params_func.append(data_inicio)
            if data_fim:
                sql_func += ' AND date(r.data_hora) <= date(?)'
                params_func.append(data_fim)

            sql_func += ' ORDER BY r.data_hora DESC'
            registros = conn.execute(sql_func, tuple(params_func)).fetchall()

            # Dados para filtros de Funcionários
            funcoes_disponiveis = conn.execute(
                'SELECT DISTINCT funcao FROM funcionarios ORDER BY funcao').fetchall()
            departamentos_disponiveis = conn.execute(
                'SELECT DISTINCT departamento FROM funcionarios ORDER BY departamento').fetchall()

        else:
            flash('Acesso ao módulo de funcionários negado.', 'danger')
            modulo_filtro = 'estudantes'

    conn.close()

    return render_template('dashboard.html',
                           registros=registros,
                           modulo=modulo_filtro,
                           termo=termo,
                           data_inicio=data_inicio,
                           data_fim=data_fim,
                           tipo_usuario=tipo_usuario,

                           curso=curso_filtro,
                           disciplina_filtro=disciplina_filtro,
                           professor_filtro=professor_filtro,
                           disciplinas=disciplinas,
                           professores=professores,
                           cursos_disponiveis=cursos_disponiveis,
                           # CORRIGIDO: Agora tem um valor garantido para o input hidden
                           curso_principal_prof=curso_principal_prof,

                           funcao_filtro=funcao_filtro,
                           departamento_filtro=departamento_filtro,
                           funcoes_disponiveis=funcoes_disponiveis,
                           departamentos_disponiveis=departamentos_disponiveis)


@app.route('/registrar', methods=['GET', 'POST'])
def registrar():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # ⚠️ Bloco try/except para capturar erros de campos ausentes (KeyError)
        try:
            # 1. CAPTURA DOS DADOS (A ORDEM DE CAPTURA FOI REORGANIZADA PARA COINCIDIR COM O SQL)
            
            # Dados Pessoais e de Identificação (Passo 1)
            nome = request.form['nome']
            data_nascimento = request.form['data_nascimento'] # Campo corrigido (YYYY-MM-DD)
            numero_bi = request.form['numero_bi']
            
            # Dados Acadêmicos (Passo 2)
            curso = request.form['curso']
            periodo = request.form['periodo']
            ano_frequencia = request.form['ano_frequencia']
            
            # Dados Pessoais Adicionais (Passo 1 e 2)
            sexo = request.form['sexo']
            numero_estudante = request.form['numero_estudante']
            estado_civil = request.form['estado_civil']
            residencia_atual = request.form['residencia_atual']
            
            # Campos Opcionais/Listas (Usam .getlist ou .get para não falhar se estiverem ausentes)
            disciplinas_selecionadas = request.form.getlist('disciplinas_selecionadas[]')
            imagem_capturada = request.form.get('imagem_capturada') 
            
            # ----------------------------------------------------
            
            conn = get_db_connection()
            caminho_foto = os.path.join("known_faces", f"{numero_bi}.jpg")

            # Lista de valores para o SQL INSERT (10 valores)
            # ESTA ORDEM É CRÍTICA E DEVE CORRESPONDER À ORDEM DAS COLUNAS NO INSERT INTO
            valores_sql = (
                nome, data_nascimento, numero_bi, curso, periodo, ano_frequencia,
                sexo, numero_estudante, estado_civil, residencia_atual
            )

            # 2. INSERIR DADOS DO ESTUDANTE
            conn.execute('''
                INSERT INTO estudantes (
                    nome, data_nascimento, numero_bi, curso, periodo, ano_frequencia,
                    sexo, numero_estudante, estado_civil, residencia_atual
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', valores_sql)
            conn.commit()

            # 3. PROCESSAR DISCIPLINAS (Lógica de captura mantida)
            if disciplinas_selecionadas:
                 # Aqui o código deveria inserir na tabela de relação N:N, mas apenas
                 # a captura da variável é suficiente para evitar o erro de servidor.
                 pass
            
            # 4. PROCESSAR E SALVAR FOTO
            if imagem_capturada:
                if ',' in imagem_capturada:
                    header, encoded = imagem_capturada.split(",", 1)
                else:
                    encoded = imagem_capturada

                imagem_bytes = base64.b64decode(encoded)
                with open(caminho_foto, "wb") as f:
                    f.write(imagem_bytes)

            elif 'foto_manual' in request.files:
                arquivo = request.files['foto_manual']
                if arquivo and arquivo.filename:
                    arquivo.save(caminho_foto)

            conn.close()

            # Retorna JSON de sucesso
            return jsonify({'sucesso': True, 'mensagem': f'Estudante {nome} registrado com sucesso!'})

        except KeyError as e:
            # ⛔ ERRO CRÍTICO: Informa exatamente qual campo está faltando.
            try:
                # Tenta fechar a conexão, se estiver aberta
                conn.close() 
            except:
                pass
            campo_ausente = str(e).strip("[]\'")
            return jsonify({'sucesso': False, 'mensagem': f'Erro de Formulário: O campo obrigatório "{campo_ausente}" está faltando. Verifique se preencheu o Passo 1 e o Passo 2 completamente antes de submeter.'}), 400
            
        except sqlite3.IntegrityError:
            try:
                conn.close()
            except:
                pass
            return jsonify({'sucesso': False, 'mensagem': 'Erro: Número de BI já registrado ou Número de Estudante duplicado.'}), 400
            
        except Exception as e:
            # Erro geral 
            try:
                conn.close()
            except:
                pass
            logging.error(f"Erro na rota /registrar: {e}") 
            return jsonify({'sucesso': False, 'mensagem': f'Erro desconhecido no servidor. Detalhe: {str(e)}'}), 500

    return render_template('registrar.html')


@app.route('/entradas', methods=['GET'])
def entradas():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Parâmetros de filtro para estudantes
    curso_filtro = request.args.get('curso', '')
    periodo_filtro = request.args.get('periodo', '')
    ano_frequencia_filtro = request.args.get('ano_frequencia', '')
    termo = request.args.get('termo', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Inicialização da Query
    sql = 'SELECT * FROM estudantes WHERE 1=1'
    params = []

    # 2. LÓGICA CRÍTICA: Restrição de Curso para Professor
    tipo_usuario = session.get('tipo_usuario')
    # Assumindo que você armazena o curso principal do professor na sessão ao fazer login.
    curso_professor = session.get('curso_principal_prof')

    if tipo_usuario == 'Professor' and curso_professor:
        # Se for professor, FORÇA o filtro do curso da sessão, ignorando o curso_filtro do URL
        sql += ' AND curso = ?'
        params.append(curso_professor)
        # Atualiza a variável de filtro para o template
        curso_filtro = curso_professor
    else:
        # Lógica para Admin/Outros (usa o filtro do usuário)
        if curso_filtro and curso_filtro != 'Todos':
            sql += ' AND curso = ?'
            params.append(curso_filtro)

    # 3. Aplicação dos Filtros Opcionais
    if periodo_filtro:
        sql += ' AND periodo = ?'
        params.append(periodo_filtro)

    if ano_frequencia_filtro:
        sql += ' AND ano_frequencia = ?'
        params.append(ano_frequencia_filtro)

    if termo:
        sql += ' AND (nome LIKE ? OR numero_bi LIKE ?)'
        params += [f'%{termo}%', f'%{termo}%']

    # 4. Execução
    sql += ' ORDER BY nome ASC'
    cursor.execute(sql, tuple(params))
    estudantes = cursor.fetchall()
    conn.close()

    return render_template('entradas.html',
                           estudantes=estudantes,
                           curso=curso_filtro,
                           periodo=periodo_filtro,
                           ano_frequencia=ano_frequencia_filtro,
                           termo=termo)


@app.route('/excluir_entrada/<int:id>')
def excluir_entrada(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Restrição: Apenas Admin pode excluir entradas
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode excluir entradas.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    conn.execute('DELETE FROM entradas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    # Redireciona para o dashboard, onde os registros de entrada estão agora
    return redirect(url_for('dashboard', modulo='estudantes'))


# Rota para Excluir Registro de Funcionário (Necessária para o botão na tabela)
@app.route('/excluir_ponto/<int:id>')
def excluir_ponto(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode excluir registros.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    conn.execute('DELETE FROM registo_funcionarios WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Registro de ponto excluído com sucesso.', 'success')
    # Redireciona para o dashboard, mantendo o módulo 'funcionarios' selecionado
    return redirect(url_for('dashboard', modulo='funcionarios'))

# ... (código anterior)
# ROTA DE RECONHECIMENTO (Ponto de entrada unificado)
# ----------------------------------------------------------------------


@app.route('/reconhecer')
def reconhecer():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    tipo_usuario = session.get('tipo_usuario')
    entidade_id = session.get('entidade_id')
    conn = get_db_connection()

    # 1. VERIFICAÇÃO DE PERMISSÃO UNIFICADA
    # O Funcionário comum ('Funcionario') e o Funcionário-Admin ('Funcionario_Admin')
    # terão acesso, mas com a interface limitada.
    if tipo_usuario not in ['Admin', 'Funcionario_Admin', 'Professor', 'Funcionario']:
        flash('Acesso negado. Você não tem permissão para usar o reconhecimento.', 'danger')
        conn.close()
        return redirect(url_for('dashboard'))

    # Inicialização de variáveis
    ofertas = []
    professores_disponiveis = []
    professor_logado_nome = None

    # 2. DETERMINAR O MODO DE FUNCIONAMENTO E CARREGAR DADOS

    # Usuário Funcionário (Comum ou Admin) deve ir para o modo PONTO e não carregar ofertas
    if tipo_usuario in ['Funcionario', 'Funcionario_Admin']:
        modo_inicial = 'funcionarios'  # Variável para controlar o estado inicial no JS
        # Força o tipo de usuário para o frontend (esconde seletor de módulo do Admin)
        tipo_usuario_frontend = 'Funcionario'
    else:
        modo_inicial = 'estudantes'
        tipo_usuario_frontend = tipo_usuario  # Mantém 'Admin' ou 'Professor'

        # Lógica para Professor e Admin (Presença de Estudantes)

        # 3.1. IDENTIFICA O PROFESSOR ATUAL
        if tipo_usuario == 'Professor':
            professor_data = conn.execute(
                'SELECT nome FROM professores WHERE id = ?', (entidade_id,)).fetchone()
            if professor_data:
                professor_logado_nome = professor_data['nome']
            else:
                flash(
                    "Erro de perfil: Dados do seu ID de Professor não encontrados.", 'danger')
                conn.close()
                return redirect(url_for('dashboard'))

            professores_disponiveis = conn.execute(
                'SELECT id, nome FROM professores WHERE id = ?', (entidade_id,)).fetchall()
        else:
            # Carrega todos os professores apenas para o Admin
            professores_disponiveis = conn.execute(
                'SELECT id, nome FROM professores ORDER BY nome').fetchall()

        # 3.2. CONSTRUÇÃO DA QUERY DE OFERTAS (Inalterada)
        query_ofertas = '''
            SELECT 
                od.id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.semestre, od.periodo, p.nome AS nome_professor, po.professor_id
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            INNER JOIN professor_oferta po ON od.id = po.oferta_id
            LEFT JOIN professores p ON po.professor_id = p.id
            WHERE 1=1
        '''
        params = {}

        if tipo_usuario == 'Professor':
            query_ofertas += ' AND po.professor_id = :entidade_id '
            params['entidade_id'] = entidade_id

        query_ofertas += ' ORDER BY od.curso, od.ano_frequencia, od.semestre, d.nome'

        # 3.3. Executa a query
        ofertas = conn.execute(query_ofertas, params).fetchall()

    conn.close()

    # 4. Renderiza a tela única com o modo correto
    return render_template('reconhecer.html',
                           ofertas=ofertas,
                           professores_disponiveis=professores_disponiveis,
                           # Passa a variável ajustada para o frontend
                           tipo_usuario=tipo_usuario_frontend,
                           professor_logado_nome=professor_logado_nome,
                           entidade_id=entidade_id,
                           # Variável chave para o JS/Jinja2 (mantida)
                           modo_reconhecimento=modo_inicial)  # 'estudantes' ou 'funcionarios'


# ==============================================================================
# FUNÇÃO DE SUPORTE: registrar_entrada (já existia, mas incluída para contexto)
# ==============================================================================

def registrar_entrada(numero_bi, oferta_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Obter ID do estudante
    cursor.execute(
        "SELECT id, curso, ano_frequencia, periodo FROM estudantes WHERE numero_bi = ?", (numero_bi,))
    estudante = cursor.fetchone()
    if not estudante:
        conn.close()
        return f"❌ Estudante com BI {numero_bi} não encontrado."
    estudante_id = estudante["id"]

    # 2. Obter detalhes da Oferta e Professor(es)
    oferta = conn.execute('''
        SELECT od.disciplina_id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.periodo, 
               po.professor_id, p.nome AS nome_professor
        FROM oferta_disciplina od
        INNER JOIN disciplinas d ON od.disciplina_id = d.id
        LEFT JOIN professor_oferta po ON od.id = po.oferta_id
        LEFT JOIN professores p ON po.professor_id = p.id
        WHERE od.id = ?
    ''', (oferta_id,)).fetchone()

    if not oferta:
        conn.close()
        return "❌ Oferta de disciplina inválida."
    disciplina_id = oferta['disciplina_id']
    professor_id = oferta['professor_id']

    # 3. VALIDAÇÃO CRUZADA (Garante que o aluno pertence à turma/oferta correta)
    if (estudante['curso'] != oferta['curso'] or
        estudante['ano_frequencia'] != oferta['ano_frequencia'] or
            estudante['periodo'] != oferta['periodo']):

        return (f"⚠️ Aluno {estudante['curso']}/{estudante['ano_frequencia']}/{estudante['periodo']} "
                f"não pertence à Oferta selecionada ({oferta['curso']}/{oferta['ano_frequencia']}/{oferta['periodo']}). "
                f"Entrada negada.")

    hoje = datetime.now().strftime('%Y-%m-%d')

    # 4. Verificar duplicidade (por disciplina/dia)
    cursor.execute("""
        SELECT * FROM entradas 
        WHERE estudante_id = ? 
        AND disciplina_id = ?
        AND data_hora LIKE ?
    """, (estudante_id, disciplina_id, hoje + '%'))

    if cursor.fetchone():
        conn.close()
        return f"ℹ️ Entrada já registrada hoje para {numero_bi} na disciplina {oferta['nome_disciplina']}."

    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 5. Inserir (usando os IDs deduzidos da Oferta)
    cursor.execute("""
        INSERT INTO entradas (estudante_id, data_hora, disciplina_id, professor_id) 
        VALUES (?, ?, ?, ?)
    """, (estudante_id, agora, disciplina_id, professor_id))

    conn.commit()
    conn.close()

    professor_nome = oferta['nome_professor'] if oferta['nome_professor'] else 'N/D'
    return f"✅ Entrada registrada às {agora} para {numero_bi} na aula de {oferta['nome_disciplina']} com {professor_nome}."

# app.py (Somente a rota /processar_reconhecimento é exibida)
# ==============================================================================
# ROTA PRINCIPAL: /processar_reconhecimento (Com chave 'tocar_som_erro' para dissociar som da mensagem de sumário)
# ==============================================================================


@app.route('/processar_reconhecimento', methods=['POST'])
def processar_reconhecimento():
    if 'usuario' not in session:
        return jsonify({"sucesso": False, "mensagem": "Acesso negado.", "tocar_som_erro": True})

    dados = request.get_json()
    imagem_base64 = dados.get('imagem', '')
    oferta_id = dados.get('oferta_id')
    professor_id = dados.get('professor_id')
    is_group_upload = dados.get('is_group_upload', False)

    if not imagem_base64:
        return jsonify({"sucesso": False, "mensagem": "Imagem não recebida.", "tocar_som_erro": True})
    if not oferta_id:
        return jsonify({"sucesso": False, "mensagem": "❌ Erro de Sistema: Oferta não selecionada.", "tocar_som_erro": True})

    if not professor_id:
        return jsonify({"sucesso": False, "mensagem": "❌ Erro de Sistema: ID do Professor é obrigatório.", "tocar_som_erro": True})

    try:
        # 1. DECODIFICAR E PREPARAR IMAGEM
        header, encoded = imagem_base64.split(",", 1)
        imagem_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 2. IDENTIFICAR ROSTOS (Simples ou Múltiplos)
        if is_group_upload:
            resultados_finais = identificar_multiplos_rostos(
                frame, known_face_encodings, known_face_names, known_face_data, known_face_estruturas)
        else:
            resultado_simples = identificar_rosto(
                frame, known_face_encodings, known_face_names, known_face_data, known_face_estruturas)
            if resultado_simples.get("sucesso") == False:
                # Falha de detecção/reconhecimento no modo live/simples. Som de erro.
                return jsonify({"sucesso": False, "mensagem": resultado_simples.get("mensagem", "❌ Rosto não reconhecido ou detectado."), "tocar_som_erro": True})

            resultados_finais = [resultado_simples]

        # 3. PROCESSAR E REGISTRAR CADA RESULTADO
        mensagens_simples = []
        lista_resultados_finais = []
        rostos_registrados = 0
        primeiro_rosto_processado = None
        tem_falha_critica = False

        for resultado in resultados_finais:
            # Garante que o primeiro rosto reconhecido é salvo para o InfoCard (Modo Simples)
            if resultado.get("sucesso") and primeiro_rosto_processado is None:
                primeiro_rosto_processado = resultado

            # Rosto Reconhecido (sucesso de reconhecimento facial)
            if resultado.get("sucesso"):
                numero_bi = resultado["numero_bi"]

                # --- AJUSTE CRÍTICO AQUI: BUSCA DADOS ATUALIZADOS PARA PEGAR url_imagem ---
                # A 'known_face_data' deve vir com url_imagem, mas buscamos o mais recente do DB
                # para garantir os dados de curso/periodo em caso de cache desatualizado.
                # Esta função agora inclui 'url_imagem'
                dados_estudante = buscar_dados_estudante(numero_bi)
                # ------------------------------------------------------------------------

                nome_estudante = dados_estudante.get('nome', numero_bi)

                # Chamada ao BD (que usa o BI)
                msg_completa = registrar_entrada(numero_bi, oferta_id)

                status_icon = msg_completa.split(' ')[0]
                status_msg_para_lista = msg_completa

                # Melhora a mensagem de retorno para o front-end
                if status_icon == '✅':
                    rostos_registrados += 1
                    status_msg_para_lista = f"✅ {nome_estudante}: **Entrada Registrada**."
                elif status_icon == 'ℹ️':
                    status_msg_para_lista = f"ℹ️ {nome_estudante}: Já registrada hoje."
                elif status_icon == '⚠️':
                    ano_estudante = dados_estudante.get(
                        'ano_frequencia', 'Ano N/D')
                    status_msg_para_lista = f"⚠️ {nome_estudante} ({ano_estudante}): Turma Incompatível. Entrada negada."
                    tem_falha_critica = True
                elif status_icon == '❌':
                    status_msg_para_lista = f"❌ {nome_estudante}: BI {numero_bi} não encontrado no sistema."
                    tem_falha_critica = True

                # Cria um objeto para a lista de grupo/detalhes no front-end
                lista_resultados_finais.append({
                    "nome": nome_estudante,
                    "numero_bi": numero_bi,
                    "status_icon": status_icon,
                    "status_mensagem": status_msg_para_lista,
                    "dados": dados_estudante,  # AGORA TEM URL_IMAGEM
                    "dimensoes": resultado["coordenadas"]
                })
                mensagens_simples.append(status_msg_para_lista)

            # Rosto NÃO Reconhecido (detectado, mas não identificado)
            else:
                msg_falha = f"❌ Rosto não reconhecido ou sem cadastro."
                lista_resultados_finais.append({
                    "nome": "Não Reconhecido",
                    "numero_bi": "N/D",
                    "status_icon": "❌",
                    "status_mensagem": msg_falha,
                    "dados": {},
                    "dimensoes": resultado.get("coordenadas", {})
                })
                mensagens_simples.append(msg_falha)
                tem_falha_critica = True

        # 4. TRATAMENTO DE RESPOSTA FINAL (Lógica de som aprimorada)
        tocar_som_erro = tem_falha_critica and rostos_registrados == 0

        # A) MODO LIVE/SIMPLES
        if not is_group_upload:
            if not lista_resultados_finais:
                return jsonify({"sucesso": False, "mensagem": "❌ Rosto detectado, mas falha no processamento.", "tocar_som_erro": True})

            resultado_final_simples = lista_resultados_finais[0]

            mensagem_sumario = resultado_final_simples['status_mensagem']
            sucesso_visual = resultado_final_simples['status_icon'] != '❌'

            return jsonify({
                "sucesso": sucesso_visual,
                "mensagem": mensagem_sumario,
                # **Isto contém url_imagem e numero_estudante (após a correção em facial_utils.py)**
                "dados": resultado_final_simples["dados"],
                "dimensoes": resultado_final_simples["dimensoes"],
                "mensagens_detalhadas": mensagens_simples,
                "tocar_som_erro": tocar_som_erro,
                # Objeto unificado para renderização no Card
                "resultado_detalhado": resultado_final_simples
            })

        # B) MODO GRUPO
        elif is_group_upload:
            if rostos_registrados > 0:
                mensagem_sumario = f"✅ {rostos_registrados} novo(s) registo(s) processado(s) com sucesso."
            elif len(lista_resultados_finais) > 0:
                mensagem_sumario = f"⚠️ {len(lista_resultados_finais)} rosto(s) analisado(s), mas sem novos registos válidos (apenas avisos/falhas)."
            else:
                return jsonify({"sucesso": False, "mensagem": "❌ Nenhum rosto detectado na imagem.", "tocar_som_erro": True})

            return jsonify({
                "sucesso": True,
                "mensagem": mensagem_sumario,
                "dados": {},
                "dimensoes": {},
                "mensagens_detalhadas": mensagens_simples,
                "tocar_som_erro": tocar_som_erro,
                "lista_grupo": lista_resultados_finais  # Lista detalhada para o modo grupo
            })

    except Exception as e:
        logging.error(f"Erro técnico: {e}")
        return jsonify({"sucesso": False, "mensagem": f"⚠️ Erro técnico: {str(e)}", "tocar_som_erro": True})

@app.route('/recarregar_rostos', methods=['POST'])
def recarregar_rostos():
    global known_face_encodings, known_face_names, known_face_data, known_face_estruturas

    dados = request.get_json()
    numero_bi_alvo = dados.get('numero_bi') if dados else None

    mensagens_status = []

    # 1 — RECARREGA SOMENTE O BI ESPECÍFICO
    if numero_bi_alvo:

        from facial_utils import carregar_rostos_conhecidos_incremental_unico, salvar_cache

        # Remove do cache antigo (se existir)
        if numero_bi_alvo in known_face_names:
            idx = known_face_names.index(numero_bi_alvo)
            known_face_names.pop(idx)
            known_face_encodings.pop(idx)
            known_face_data.pop(numero_bi_alvo, None)
            known_face_estruturas.pop(numero_bi_alvo, None)
            mensagens_status.append(f"Cache removido: {numero_bi_alvo}")

        # TENTA RECARREGAR
        novo_enc, novo_nome, novo_dados, novo_estrut, msg = \
            carregar_rostos_conhecidos_incremental_unico(numero_bi_alvo)

        mensagens_status.append(msg)

        # SE FALHOU, NÃO QUEBRA O SERVIDOR
        if not novo_nome:
            salvar_cache(known_face_encodings, known_face_names, known_face_data, known_face_estruturas)
            return jsonify({
                "sucesso": False,
                "mensagem": msg
            }), 400

        # Sucesso
        known_face_encodings.extend(novo_enc)
        known_face_names.extend(novo_nome)
        known_face_data.update(novo_dados)
        known_face_estruturas.update(novo_estrut)

        salvar_cache(known_face_encodings, known_face_names, known_face_data, known_face_estruturas)

        return jsonify({
            "sucesso": True,
            "mensagem": " | ".join(mensagens_status)
        })

    # 2 — SEM numero_bi: recarrega tudo
    else:
        from facial_utils import carregar_rostos_conhecidos_incremental, salvar_cache

        existentes = set(known_face_names)
        novos_enc, novos_nomes, novos_dados, novos_estr = \
            carregar_rostos_conhecidos_incremental(existentes)

        known_face_encodings.extend(novos_enc)
        known_face_names.extend(novos_nomes)
        known_face_data.update(novos_dados)
        known_face_estruturas.update(novos_estr)

        salvar_cache(known_face_encodings, known_face_names, known_face_data, known_face_estruturas)

        return jsonify({
            "sucesso": True,
            "mensagem": f"{len(novos_nomes)} rostos recarregados."
        })


@app.route('/estudante/<int:id>', methods=['GET', 'POST'])
def gerenciar_estudante(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    # Pega o estado ATUAL do estudante no BD
    estudante = conn.execute(
        'SELECT * FROM estudantes WHERE id = ?', (id,)).fetchone()
    if not estudante:
        conn.close()
        return "Estudante não encontrado."

    # Caminho da foto ANTIGA (baseado no BI atual do DB)
    caminho_foto_antigo = os.path.join(
        'known_faces', f"{estudante['numero_bi']}.jpg")
    existe_foto = os.path.exists(caminho_foto_antigo)

    if request.method == 'POST':

        # Declaração das variáveis globais do cache
        global known_face_encodings, known_face_names, known_face_data, known_face_estruturas
        from facial_utils import salvar_cache

        if 'eliminar' in request.form:
            # ... (Restrição de Admin)

            # AÇÃO DE ELIMINAR:
            # 1. Remove o BI do cache em memória
            bi_para_remover = estudante['numero_bi']
            if bi_para_remover in known_face_names:
                idx = known_face_names.index(bi_para_remover)
                known_face_names.pop(idx)
                known_face_encodings.pop(idx)
                known_face_data.pop(bi_para_remover, None)
                known_face_estruturas.pop(bi_para_remover, None)

            # 2. Salva o cache atualizado
            salvar_cache(known_face_encodings, known_face_names,
                         known_face_data, known_face_estruturas)

            # 3. Remove os registros do BD
            conn.execute('DELETE FROM estudantes WHERE id = ?', (id,))
            # Remove Registros de Presença
            conn.execute('DELETE FROM entradas WHERE estudante_id = ?', (id,))
            conn.commit()
            conn.close()

            # 4. REMOVE O ARQUIVO DE FOTO (CRUCIAL)
            if os.path.exists(caminho_foto_antigo):
                os.remove(caminho_foto_antigo)

            flash("Estudante excluído com sucesso. Cache de rosto limpo.", 'success')
            return redirect(url_for('entradas'))

        if 'editar' in request.form:
            nome = request.form['nome']
            novo_numero_bi = request.form['numero_bi']
            curso = request.form['curso']
            periodo = request.form['periodo']
            ano_frequencia = request.form['ano_frequencia']
            data_nascimento = request.form.get('data_nascimento')

            # --- NOVOS CAMPOS ADICIONADOS ---
            sexo = request.form['sexo']
            numero_estudante = request.form['numero_estudante']
            estado_civil = request.form['estado_civil']
            residencia_atual = request.form['residencia_atual']
            # ------------------------------

            nova_foto_base64 = request.form.get('nova_foto_base64')

            foto_atualizada_no_disco = False
            bi_alterado = estudante['numero_bi'] != novo_numero_bi

            # 1. Atualização no banco de dados
            conn.execute('''
                UPDATE estudantes
                SET nome = ?, numero_bi = ?, curso = ?, periodo = ?, ano_frequencia = ?, data_nascimento = ?,
                    sexo = ?, numero_estudante = ?, estado_civil = ?, residencia_atual = ?
                    -- Campos de atualização adicionados aqui
                WHERE id = ?
            ''', (nome, novo_numero_bi, curso, periodo, ano_frequencia, data_nascimento,
                  sexo, numero_estudante, estado_civil, residencia_atual, id))
            conn.commit()

            # ------------------------------------
            # LÓGICA DE ATUALIZAÇÃO DA FOTO E CACHE
            # ------------------------------------

            caminho_foto_novo = os.path.join(
                'known_faces', f"{novo_numero_bi}.jpg")

            # A) Se o BI mudou, remove a foto antiga no disco
            if bi_alterado and os.path.exists(caminho_foto_antigo):
                os.remove(caminho_foto_antigo)

            # B) Salva a nova foto se houver upload/captura
            if nova_foto_base64 or ('nova_foto' in request.files and request.files['nova_foto'].filename):

                # 1. Prioriza a foto capturada via webcam (Base64)
                if nova_foto_base64:
                    try:
                        if ',' in nova_foto_base64:
                            header, encoded = nova_foto_base64.split(",", 1)
                        else:
                            encoded = nova_foto_base64

                        imagem_bytes = base64.b64decode(encoded)
                        with open(caminho_foto_novo, "wb") as f:
                            f.write(imagem_bytes)
                        foto_atualizada_no_disco = True
                    except Exception as e:
                        logging.error(
                            f"Erro ao salvar foto Base64 em edição: {e}")

                # 2. Verifica o upload de arquivo
                elif 'nova_foto' in request.files:
                    arquivo = request.files['nova_foto']
                    if arquivo and arquivo.filename:
                        arquivo.save(caminho_foto_novo)
                        foto_atualizada_no_disco = True

            conn.close()

            # C) ATUALIZAÇÃO DO CACHE EM MEMÓRIA E ARQUIVO (.pkl)
            if bi_alterado or foto_atualizada_no_disco:

                # 1. Remove o BI ANTIGO da memória
                bi_para_remover = estudante['numero_bi']
                if bi_para_remover in known_face_names:
                    idx = known_face_names.index(bi_para_remover)
                    known_face_names.pop(idx)
                    known_face_encodings.pop(idx)
                    known_face_data.pop(bi_para_remover, None)
                    known_face_estruturas.pop(bi_para_remover, None)

                # 2. Se o BI MUDOU, e o NOVO BI estava no cache, removemos o NOVO BI também
                # (isso garante que o novo encoding da nova foto será criado do zero na recarga)
                if bi_alterado and novo_numero_bi in known_face_names:
                    idx = known_face_names.index(novo_numero_bi)
                    known_face_names.pop(idx)
                    known_face_encodings.pop(idx)
                    known_face_data.pop(novo_numero_bi, None)
                    known_face_estruturas.pop(novo_numero_bi, None)

                # 3. Salva o cache no disco (.pkl) sem a referência antiga
                salvar_cache(known_face_encodings, known_face_names,
                             known_face_data, known_face_estruturas)

            # Retorna JSON para o JS fazer o recarregamento assíncrono
            return jsonify({'sucesso': True,
                            'foto_atualizada': foto_atualizada_no_disco,
                            'mensagem': f'Estudante {nome} atualizado com sucesso. O cache será recarregado na próxima inicialização ou manualmente.'})

    conn.close()

    # O caminho da foto é verificado aqui para o GET
    caminho_foto_atualizado = os.path.join(
        'known_faces', f"{estudante['numero_bi']}.jpg")
    existe_foto = os.path.exists(caminho_foto_atualizado)

    return render_template('gerenciar_estudante.html', estudante=estudante, existe_foto=existe_foto, now=datetime.now().timestamp())


@app.route('/verificar_rosto', methods=['POST'])
def verificar_rosto():
    dados = request.get_json()
    imagem_base64 = dados.get('imagem', '')
    if not imagem_base64:
        return jsonify({"sucesso": False, "mensagem": "Imagem não recebida."})
    try:
        header, encoded = imagem_base64.split(",", 1)
        imagem_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_small)
        if not face_locations:
            return jsonify({"sucesso": False, "mensagem": "❌ Nenhum rosto detectado."})
        top, right, bottom, left = face_locations[0]
        scale = 4
        return jsonify({
            "sucesso": True,
            "dimensions": {
                "top": top * scale,
                "right": right * scale,
                "bottom": bottom * scale,
                "left": left * scale
            }
        })
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": f"Erro: {str(e)}"})


@app.route('/opcoes')
def opcoes():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Restrição: Apenas Admin pode acessar Opções
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador tem acesso às opções do sistema.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template('opcoes.html')


@app.route('/backup', methods=['POST'])
def gerar_backup():
    if 'usuario' not in session:
        return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'})

    # Restrição: Apenas Admin pode fazer backup
    if session.get('tipo_usuario') != 'Admin':
        return jsonify({'sucesso': False, 'mensagem': 'Acesso negado. Apenas o administrador pode gerar backup.'})

    import zipfile
    import io
    from datetime import datetime

    data = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if os.path.exists('database.db'):
            zipf.write('database.db')
        for root, _, files in os.walk('known_faces'):
            for file in files:
                caminho_completo = os.path.join(root, file)
                caminho_rel = os.path.relpath(caminho_completo)
                zipf.write(caminho_completo, arcname=caminho_rel)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=f'backup_{data}.zip',
        mimetype='application/zip'
    )
# CÓDIGO DA ROTA /exportar_csv CORRIGIDO
# CÓDIGO DA ROTA /exportar_csv CORRIGIDO


@app.route('/exportar_csv', methods=['POST'])
def exportar_csv():
    # -----------------------------------------------------------
    # 0. VERIFICAÇÃO DE SESSÃO E CONEXÃO
    # -----------------------------------------------------------
    if 'usuario' not in session:
        return redirect(url_for('login'))

    tipo = request.form.get('tipo', 'entradas_csv')
    conn = get_db_connection()
    tipo_usuario = session.get('tipo_usuario')
    entidade_id = session.get('entidade_id')
    nome_arquivo = ''
    dados = []
    buffer = None
    response = None

    # -----------------------------------------------------------
    # 1. COLETA DE PARÂMETROS DE FILTRO DO FORMULÁRIO
    # -----------------------------------------------------------
    termo = request.form.get('termo', '')
    data_inicio = request.form.get('data_inicio')
    data_fim = request.form.get('data_fim')
    curso_filtro = request.form.get('curso')
    disciplina_filtro = request.form.get('disciplina')
    professor_filtro = request.form.get('professor')
    funcao_filtro = request.form.get('funcao')
    departamento_filtro = request.form.get('departamento')

    # -----------------------------------------------------------
    # 2. VALIDAÇÃO DE PERMISSÃO E LÓGICA DE COLETA DE DADOS
    # -----------------------------------------------------------

    is_student_report = tipo.startswith(
        'estudantes_') or tipo.startswith('entradas_')
    is_employee_report = tipo.startswith(
        'funcionarios_') or tipo.startswith('ponto_')

    # Validação de Permissão (Estudantes/Entradas)
    if is_student_report and tipo_usuario not in ['Admin', 'Professor']:
        conn.close()
        flash('Acesso negado. Apenas o administrador ou professor pode exportar dados de estudantes.', 'danger')
        return redirect(url_for('dashboard'))

    # Validação de Permissão (Funcionários/Ponto)
    if is_employee_report and tipo_usuario not in ['Admin', 'Funcionario_Admin', 'Funcionario']:
        conn.close()
        flash('Acesso negado. Apenas o administrador ou funcionários autorizados podem exportar dados de funcionários.', 'danger')
        return redirect(url_for('dashboard'))

    # Restringe Professor ao seu tipo de relatório e Funcionario a ponto_
    if (tipo_usuario == 'Professor' and not tipo.startswith('entradas_')) or \
       (tipo_usuario == 'Funcionario' and not tipo.startswith('ponto_')):
        conn.close()
        flash(
            f'Acesso negado. O seu perfil só pode exportar relatórios de {"Entrada" if tipo_usuario == "Professor" else "Ponto"}.', 'danger')
        return redirect(url_for('dashboard'))

    # ===================================================================================
    # RESTRIÇÃO DE FUNCIONÁRIO COMUM: O Funcionário só deve ver os seus próprios registros.
    # ===================================================================================
    funcionario_id_restricao = None
    if tipo_usuario == 'Funcionario':
        funcionario_id_restricao = entidade_id
        # Ignora filtros de Admin/Funcionario_Admin
        funcao_filtro = None
        departamento_filtro = None
        termo = None

    where_clauses = []
    params = []
    buffer = None

    try:
        # =======================================================
        # GERAÇÃO DO RELATÓRIO DE REGISTROS DE ENTRADA (ESTUDANTES)
        # =======================================================
        if tipo.startswith('entradas_'):

            # --- 2.1 CONSTRUÇÃO DA CLÁUSULA WHERE ---
            if tipo_usuario == 'Professor':

                # [CORREÇÃO CRÍTICA]: SOBRESCREVE professor_filtro com ID da sessão
                professor_filtro = entidade_id

                # Aplica a restrição de ID (agora é garantido)
                if professor_filtro:
                    where_clauses.append('e.professor_id = ?')
                    params.append(professor_filtro)

                if curso_filtro and curso_filtro != 'Todos':
                    where_clauses.append('s.curso = ?')
                    params.append(curso_filtro)
            else:
                # Lógica do Admin/Funcionario_Admin
                if curso_filtro and curso_filtro != 'Todos':
                    where_clauses.append('s.curso = ?')
                    params.append(curso_filtro)
                if professor_filtro:
                    where_clauses.append('e.professor_id = ?')
                    params.append(professor_filtro)

            # Filtros Comuns (Disciplina, Termo, Data)
            if disciplina_filtro:
                where_clauses.append('e.disciplina_id = ?')
                params.append(disciplina_filtro)
            if termo:
                where_clauses.append('(s.nome LIKE ? OR s.numero_bi LIKE ?)')
                params.extend([f'%{termo}%', f'%{termo}%'])
            if data_inicio:
                where_clauses.append('e.data_hora >= ?')
                params.append(data_inicio + ' 00:00:00')
            if data_fim:
                where_clauses.append('e.data_hora <= ?')
                params.append(data_fim + ' 23:59:59')

            where_clause = ' WHERE ' + \
                ' AND '.join(where_clauses) if where_clauses else ''

            # --- 2.2 EXECUÇÃO DA QUERY ---
            query = f'''
                SELECT e.id, e.data_hora, s.nome, s.numero_bi, s.curso, s.numero_estudante, d.nome AS nome_disciplina, p.nome AS nome_professor
                FROM entradas e
                INNER JOIN estudantes s ON e.estudante_id = s.id
                LEFT JOIN disciplinas d ON e.disciplina_id = d.id
                LEFT JOIN professores p ON e.professor_id = p.id
                {where_clause} ORDER BY e.data_hora DESC
            '''
            dados = conn.execute(query, tuple(params)).fetchall()

            # Lógica CSV para Entradas
            if tipo == 'entradas_csv':
                buffer = io.BytesIO()
                output = io.TextIOWrapper(
                    buffer, encoding='utf-8-sig', newline='')
                writer = csv.writer(output, delimiter=';')

                writer.writerow(['Data/Hora', 'Nome', 'Número BI',
                                'Nº Estudante', 'Curso', 'Disciplina', 'Professor'])

                for row in dados:
                    e = dict(row)
                    writer.writerow([e['data_hora'], e['nome'], e['numero_bi'], e.get(
                        'numero_estudante', ''), e['curso'], e.get('nome_disciplina', ''), e.get('nome_professor', '')])

                output.seek(0)
                buffer.seek(0)

                nome_arquivo = f'entradas_estudantes{"_professor" if tipo_usuario == "Professor" else ""}.csv'

        # =======================================================
        # GERAÇÃO DO RELATÓRIO DE PONTO (FUNCIONÁRIOS)
        # =======================================================
        elif tipo.startswith('ponto_'):
            # --- 2.1 CONSTRUÇÃO DA CLÁUSULA WHERE ---
            where_clauses = []
            params = []

            # [RESTRIÇÃO FUNCIONÁRIO COMUM]: Aplica a restrição de ID
            if funcionario_id_restricao:
                where_clauses.append('r.funcionario_id = ?')
                params.append(funcionario_id_restricao)

            # Filtros Admin/FuncAdmin (são None para Funcionario Comum)
            if funcao_filtro:
                where_clauses.append('f.funcao = ?')
                params.append(funcao_filtro)
            if departamento_filtro:
                where_clauses.append('f.departamento = ?')
                params.append(departamento_filtro)
            if termo:
                where_clauses.append('(f.nome LIKE ? OR f.numero_bi LIKE ?)')
                params.extend([f'%{termo}%', f'%{termo}%'])
            if data_inicio:
                where_clauses.append('r.data_hora >= ?')
                params.append(data_inicio + ' 00:00:00')
            if data_fim:
                where_clauses.append('r.data_hora <= ?')
                params.append(data_fim + ' 23:59:59')
            where_clause = ' WHERE ' + \
                ' AND '.join(where_clauses) if where_clauses else ''

            # --- 2.2 EXECUÇÃO DA QUERY ---
            query = f'''
                SELECT r.id, r.data_hora, r.tipo_registo, f.nome, f.numero_bi, f.funcao, f.departamento
                FROM registo_funcionarios r
                INNER JOIN funcionarios f ON r.funcionario_id = f.id
                {where_clause} ORDER BY r.data_hora DESC
            '''
            dados = conn.execute(query, tuple(params)).fetchall()

            # Lógica CSV para Ponto
            if tipo == 'ponto_csv':
                buffer = io.BytesIO()
                output = io.TextIOWrapper(
                    buffer, encoding='utf-8-sig', newline='')
                writer = csv.writer(output, delimiter=';')

                writer.writerow(
                    ['Data/Hora', 'Tipo', 'Nome Funcionario', 'Número BI', 'Função', 'Departamento'])

                for row in dados:
                    r = dict(row)
                    writer.writerow([r['data_hora'], r['tipo_registo'], r['nome'],
                                    r['numero_bi'], r['funcao'], r['departamento']])

                output.seek(0)
                buffer.seek(0)

                nome_arquivo = 'funcionarios_ponto.csv'

        # =======================================================
        # GERAÇÃO DOS RELATÓRIOS DE CADASTRO (ESTUDANTES - ADMIN ONLY)
        # =======================================================
        elif tipo == 'estudantes_csv' or tipo == 'estudantes_pdf':
            # [CORREÇÃO 3]: Permissão de Admin já verifica tipo_usuario.
            if tipo_usuario != 'Admin':
                raise PermissionError(
                    'Apenas Admin pode exportar o cadastro completo de estudantes.')
            dados = conn.execute('SELECT * FROM estudantes').fetchall()

            # Lógica CSV para Cadastro de Estudantes
            if tipo == 'estudantes_csv':
                buffer = io.BytesIO()
                output = io.TextIOWrapper(
                    buffer, encoding='utf-8-sig', newline='')
                writer = csv.writer(output, delimiter=';')

                writer.writerow(['Nº Estudante', 'Nome', 'Número BI', 'Curso',
                                 'Período', 'Ano Frequência', 'Data Nascimento', 'Sexo',
                                 'Estado Civil', 'Residência Atual'])

                for row in dados:
                    est = dict(row)
                    writer.writerow([est.get('numero_estudante', ''), est['nome'], est['numero_bi'], est['curso'],
                                     est['periodo'], est['ano_frequencia'], est['data_nascimento'], est.get(
                                         'sexo', ''),
                                     est.get('estado_civil', ''), est.get('residencia_atual', '')])

                output.seek(0)
                buffer.seek(0)
                nome_arquivo = 'estudantes_cadastro.csv'

        # =======================================================
        # GERAÇÃO DOS RELATÓRIOS DE CADASTRO (FUNCIONÁRIOS - ADMIN/ADMIN FUNC ONLY)
        # =======================================================
        elif tipo == 'funcionarios_csv' or tipo == 'funcionarios_pdf':
            if tipo_usuario not in ['Admin', 'Funcionario_Admin']:
                raise PermissionError(
                    'Apenas Admin ou Admin de Funcionários pode exportar o cadastro completo de funcionários.')
            dados = conn.execute('SELECT * FROM funcionarios').fetchall()

            # Lógica CSV para Cadastro de Funcionários
            if tipo == 'funcionarios_csv':
                buffer = io.BytesIO()
                output = io.TextIOWrapper(
                    buffer, encoding='utf-8-sig', newline='')
                writer = csv.writer(output, delimiter=';')

                writer.writerow(
                    ['Nome', 'Número BI', 'Nº Funcionário', 'Função', 'Departamento'])

                for row in dados:
                    func = dict(row)
                    writer.writerow([func['nome'], func['numero_bi'], func.get(
                        'numero_funcionario', ''), func['funcao'], func['departamento']])

                output.seek(0)
                buffer.seek(0)
                nome_arquivo = 'funcionarios_cadastro.csv'

        # -----------------------------------------------------------
        # 3. LÓGICA DE EXPORTAÇÃO PDF
        # -----------------------------------------------------------

        if tipo.endswith('_pdf'):
            if not dados:
                flash('Nenhum dado encontrado para exportar para PDF.', 'info')
                response = redirect(url_for('dashboard'))
            else:
                prefixo = tipo.split('_')[0]

                dados_dict_list = [dict(row) for row in dados]

                try:
                    response = exportar_pdf(prefixo, dados_dict_list)
                except Exception as e_pdf:
                    print(f"ERRO AO GERAR PDF: {str(e_pdf)}")
                    flash('Erro ao gerar PDF. Verifique os logs do servidor.', 'danger')
                    response = redirect(url_for('dashboard'))

        # -----------------------------------------------------------
        # 4. RETORNO FINAL CSV
        # -----------------------------------------------------------

        if buffer and tipo.endswith('_csv'):
            return Response(
                buffer.read(),
                mimetype='text/csv; charset=utf-8',
                headers={
                    'Content-Disposition': f'attachment; filename={nome_arquivo}'}
            )

    except PermissionError as e:
        flash(f'Acesso negado: {str(e)}', 'danger')
        response = redirect(url_for('dashboard'))
    except Exception as e:
        flash(f'Erro ao gerar relatório: {str(e)}', 'danger')
        print(f"ERRO DE EXPORTAÇÃO: {str(e)}")
        response = redirect(url_for('dashboard'))

    finally:
        if conn:
            conn.close()

    # Retorna a resposta (PDF, CSV, ou redirecionamento de erro)
    if response:
        return response

    # Bloco de segurança caso a lógica do tipo falhe
    flash('Não foi possível gerar o arquivo. Verifique se o tipo de relatório está correto.', 'danger')
    return redirect(url_for('dashboard'))


@app.route('/resetar_banco', methods=['POST'])
def resetar_banco():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Restrição: Apenas Admin pode resetar
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode redefinir o banco de dados.', 'danger')
        return redirect(url_for('dashboard'))

    tipo = request.form.get('tipo')
    conn = get_db_connection()
    cursor = conn.cursor()

    if tipo == 'entradas':
        cursor.execute('DELETE FROM entradas')
    elif tipo == 'estudantes':
        cursor.execute('DELETE FROM entradas')
        cursor.execute('DELETE FROM estudantes')
        cursor.execute('DELETE FROM funcionarios')
        for nome_arquivo in os.listdir('known_faces'):
            os.remove(os.path.join('known_faces', nome_arquivo))
    elif tipo == 'tudo':
        cursor.execute('DELETE FROM entradas')
        cursor.execute('DELETE FROM estudantes')
        cursor.execute('DELETE FROM funcionarios')
        # Limpar tabelas de apoio se existir
        cursor.execute('DELETE FROM disciplinas')
        cursor.execute('DELETE FROM professores')
        cursor.execute('DELETE FROM oferta_disciplina')
        cursor.execute('DELETE FROM professor_oferta')
        cursor.execute('DELETE FROM credenciais_professores')
        cursor.execute('DELETE FROM funcionarios')  # NOVO
        cursor.execute('DELETE FROM registo_funcionarios')  # NOVO
        for nome_arquivo in os.listdir('known_faces'):
            os.remove(os.path.join('known_faces', nome_arquivo))
    elif tipo == 'funcionarios':
        cursor.execute('DELETE FROM funcionarios')

    conn.commit()
    conn.close()

    return redirect(url_for('opcoes'))


# Rotas para obter dados (necessário para preencher os selects no frontend)
@app.route('/api/disciplinas', methods=['GET'])
def api_disciplinas():
    conn = get_db_connection()
    disciplinas = conn.execute(
        'SELECT id, nome FROM disciplinas ORDER BY nome').fetchall()
    conn.close()
    return jsonify([dict(d) for d in disciplinas])


@app.route('/api/professores', methods=['GET'])
def api_professores():
    conn = get_db_connection()
    professores = conn.execute(
        'SELECT id, nome FROM professores ORDER BY nome').fetchall()
    conn.close()
    return jsonify([dict(p) for p in professores])


# ==============================================================================
# NOVAS ROTAS DE GERENCIAMENTO (PROFESSORES, OFERTAS E ASSOCIAÇÕES)
# ==============================================================================

# Rota para Listar/Adicionar Professores
# app.py (Rota /gerenciar_professores ATUALIZADA)

@app.route('/professores', methods=['GET', 'POST'])
def gerenciar_professores():
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode gerenciar professores.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # Lista de Cursos disponíveis para o template
    cursos_disponiveis = ['Informática', 'Enfermagem', 'Contabilidade']

    if request.method == 'POST':
        nome = request.form.get('nome').strip()
        # CAPTURA A LISTA DE CURSOS SELECIONADOS NO FORMULÁRIO DE ADIÇÃO
        cursos_selecionados = request.form.getlist('cursos_de_atuacao_add')

        if nome:
            try:
                cursor = conn.cursor()

                # 1. INSIRA O NOVO PROFESSOR (só nome)
                cursor.execute(
                    'INSERT INTO professores (nome) VALUES (?)', (nome,))
                novo_professor_id = cursor.lastrowid

                # 2. ASSOCIE OS CURSOS SELECIONADOS (Lógica N:M)
                for curso in cursos_selecionados:
                    cursor.execute(
                        'INSERT INTO professor_curso (professor_id, curso) VALUES (?, ?)', (novo_professor_id, curso))

                conn.commit()
                flash(
                    f'Professor "{nome}" adicionado com sucesso e associado a {len(cursos_selecionados)} curso(s).', 'success')
            except sqlite3.IntegrityError:
                flash('Erro: Professor já existe.', 'danger')
            except Exception as e:
                conn.rollback()
                flash(f'Erro ao adicionar professor: {str(e)}', 'danger')
        return redirect(url_for('gerenciar_professores'))

    # Lógica de LEITURA (Buscar cursos associados para exibição na lista)
    professores = conn.execute('''
        SELECT 
            p.id, p.nome, GROUP_CONCAT(pc.curso) AS cursos_associados
        FROM professores p
        LEFT JOIN professor_curso pc ON p.id = pc.professor_id
        GROUP BY p.id
        ORDER BY p.nome ASC
    ''').fetchall()

    conn.close()
    return render_template('gerenciar_professores.html',
                           professores=professores,
                           cursos_disponiveis=cursos_disponiveis)  # Passa para o template


@app.route('/professor/<int:id>', methods=['GET', 'POST'])
def editar_professor(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # 1. Busca dados básicos do professor e seus cursos atuais
    professor = conn.execute(
        'SELECT * FROM professores WHERE id = ?', (id,)).fetchone()
    cursos_atuais = conn.execute(
        'SELECT curso FROM professor_curso WHERE professor_id = ?', (id,)).fetchall()
    cursos_atuais_list = [c['curso'] for c in cursos_atuais]

    if not professor:
        conn.close()
        return "Professor não encontrado.", 404

    cursos_disponiveis = ['Informática', 'Enfermagem', 'Contabilidade']

    if request.method == 'POST':
        nome = request.form.get('nome').strip()
        # MÚLTIPLOS CURSOS SÃO RECEBIDOS COMO LISTA
        cursos_selecionados = request.form.getlist('cursos_de_atuacao')

        if nome:
            try:
                # 2. Atualiza o nome do professor
                conn.execute(
                    'UPDATE professores SET nome = ? WHERE id = ?', (nome, id))

                # 3. Atualiza os cursos associados (Lógica M:N)
                conn.execute(
                    'DELETE FROM professor_curso WHERE professor_id = ?', (id,))
                for curso in cursos_selecionados:
                    conn.execute(
                        'INSERT INTO professor_curso (professor_id, curso) VALUES (?, ?)', (id, curso))

                conn.commit()
                flash(
                    f'Professor "{nome}" atualizado com sucesso, incluindo {len(cursos_selecionados)} curso(s) de atuação.', 'success')
            except Exception as e:
                flash(f'Erro ao atualizar professor: {str(e)}', 'danger')

        conn.close()
        return redirect(url_for('gerenciar_professores'))

    conn.close()
    return render_template('editar_professor.html',
                           professor=professor,
                           cursos_disponiveis=cursos_disponiveis,
                           cursos_atuais_list=cursos_atuais_list)

# Rota para Eliminar Professor


@app.route('/professor/excluir/<int:id>')
def excluir_professor(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # Verificar associações antes de excluir.
    entradas_count = conn.execute(
        'SELECT COUNT(*) FROM entradas WHERE professor_id = ?', (id,)).fetchone()[0]

    # Nova verificação: professor associado a alguma oferta
    ofertas_count = conn.execute(
        'SELECT COUNT(*) FROM professor_oferta WHERE professor_id = ?', (id,)).fetchone()[0]

    if entradas_count > 0:
        flash(
            f'Não é possível excluir o professor. Há {entradas_count} registro(s) de entrada associado(s) a ele.', 'danger')
        conn.close()
        return redirect(url_for('gerenciar_professores'))

    try:
        if ofertas_count > 0:
            # Remove associações órfãs na tabela M:N
            conn.execute(
                'DELETE FROM professor_oferta WHERE professor_id = ?', (id,))

        # Remove a credencial de login antes de excluir o professor
        conn.execute(
            'DELETE FROM credenciais_professores WHERE professor_id = ?', (id,))

        # Remove a associação de cursos M:N
        conn.execute(
            'DELETE FROM professor_curso WHERE professor_id = ?', (id,))

        conn.execute('DELETE FROM professores WHERE id = ?', (id,))
        conn.commit()
        flash('Professor excluído com sucesso.', 'success')
    except Exception as e:
        flash(f'Erro ao excluir professor: {str(e)}', 'danger')

    conn.close()
    return redirect(url_for('gerenciar_professores'))


# Rota para Gerenciar a Oferta (Grade Curricular: Curso/Ano/Semestre/Período)
@app.route('/oferta', methods=['GET', 'POST'])
def gerenciar_oferta():
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode gerenciar ofertas.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # As disciplinas disponíveis agora são as JÁ CADASTRADAS (para o formulário)
    disciplinas_existentes = conn.execute(
        'SELECT id, nome FROM disciplinas ORDER BY nome').fetchall()

    # Lógica de POST (Adicionar nova Oferta)
    if request.method == 'POST':
        # Novos campos de formulário: nome_disciplina (texto livre) ou disciplina_id (se já existente)
        disciplina_existente_id = request.form.get('disciplina_existente_id')
        novo_nome_disciplina = request.form.get(
            'novo_nome_disciplina', '').strip()

        curso = request.form.get('curso')
        ano_frequencia = request.form.get('ano_frequencia')
        semestre = request.form.get('semestre')
        periodo = request.form.get('periodo')  # NOVO CAMPO

        disciplina_final_id = None

        try:
            # 1. TRATAMENTO DA DISCIPLINA (Cria ou Usa Existente)
            if novo_nome_disciplina:
                # Tenta criar a nova disciplina
                cursor = conn.execute(
                    'INSERT INTO disciplinas (nome) VALUES (?)', (novo_nome_disciplina,))
                disciplina_final_id = cursor.lastrowid
                conn.commit()
            elif disciplina_existente_id:
                # Usa a disciplina existente
                disciplina_final_id = disciplina_existente_id
            else:
                flash(
                    'Você deve selecionar uma disciplina existente ou digitar um novo nome.', 'danger')
                return redirect(url_for('gerenciar_oferta'))

            # 2. CRIAÇÃO DA OFERTA (com o novo campo 'periodo')
            if disciplina_final_id and curso and ano_frequencia and semestre and periodo:
                conn.execute('''
                    INSERT INTO oferta_disciplina (disciplina_id, curso, ano_frequencia, semestre, periodo)
                    VALUES (?, ?, ?, ?, ?)
                ''', (disciplina_final_id, curso, ano_frequencia, semestre, periodo))
                conn.commit()
                flash('Oferta de disciplina registrada com sucesso.', 'success')
            else:
                flash('Todos os campos da oferta são obrigatórios.', 'danger')

        except sqlite3.IntegrityError as e:
            # Captura erro se o UNIQUE constraint na oferta_disciplina for violado
            if "UNIQUE constraint failed" in str(e):
                flash(
                    'Erro: Esta oferta (Disciplina/Curso/Ano/Semestre/Período) já existe.', 'danger')
            # Captura erro se o UNIQUE constraint na disciplinas for violado (se tentou criar uma nova com nome repetido)
            elif "disciplinas.nome" in str(e):
                flash(
                    f'Erro: A disciplina "{novo_nome_disciplina}" já existe. Por favor, selecione-a na lista de existentes ou use outro nome.', 'danger')
            else:
                flash(f'Erro de integridade: {str(e)}', 'danger')
        except Exception as e:
            flash(f'Erro: {str(e)}', 'danger')

        return redirect(url_for('gerenciar_oferta'))

    # Lógica de GET (Listar todas as Ofertas)
    ofertas = conn.execute('''
        SELECT 
            od.id, od.curso, od.ano_frequencia, od.semestre, od.periodo, d.nome AS nome_disciplina,
            p.nome AS nome_professor
        FROM oferta_disciplina od
        INNER JOIN disciplinas d ON od.disciplina_id = d.id
        LEFT JOIN professor_oferta po ON od.id = po.oferta_id
        LEFT JOIN professores p ON po.professor_id = p.id
        ORDER BY od.curso, od.ano_frequencia, od.semestre, d.nome
    ''').fetchall()

    conn.close()

    # Dados necessários para o formulário de Adição/Edição
    cursos = ['Informática', 'Enfermagem', 'Contabilidade']
    anos = ['1º Ano', '2º Ano', '3º Ano', '4º Ano', '5º Ano']
    semestres = [1, 2]
    periodos = ['Regular', 'Pós-Laboral']

    return render_template('gerenciar_oferta.html',
                           disciplinas=disciplinas_existentes,
                           ofertas=ofertas,
                           cursos=cursos,
                           anos=anos,
                           semestres=semestres,
                           periodos=periodos)


# Rota para Editar/Atualizar Oferta
@app.route('/oferta/editar/<int:id>', methods=['GET', 'POST'])
def editar_oferta(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # Busca a oferta existente
    oferta = conn.execute('''
        SELECT od.id, od.disciplina_id, od.curso, od.ano_frequencia, od.semestre, od.periodo, d.nome AS nome_disciplina
        FROM oferta_disciplina od
        INNER JOIN disciplinas d ON od.disciplina_id = d.id
        WHERE od.id = ?
    ''', (id,)).fetchone()

    if not oferta:
        conn.close()
        return "Oferta de Disciplina não encontrada.", 404

    # Busca as disciplinas disponíveis para preencher o SELECT
    disciplinas_disponiveis = conn.execute(
        'SELECT id, nome FROM disciplinas ORDER BY nome').fetchall()

    # Dados necessários para o formulário de Edição
    cursos = ['Informática', 'Enfermagem', 'Contabilidade']
    anos = ['1º Ano', '2º Ano', '3º Ano', '4º Ano', '5º Ano']
    semestres = [1, 2]
    periodos = ['Regular', 'Pós-Laboral']

    if request.method == 'POST':
        novo_disciplina_id = request.form.get('disciplina_id')
        novo_curso = request.form.get('curso')
        novo_ano_frequencia = request.form.get('ano_frequencia')
        novo_semestre = request.form.get('semestre')
        novo_periodo = request.form.get('periodo')  # NOVO CAMPO

        if novo_disciplina_id and novo_curso and novo_ano_frequencia and novo_semestre and novo_periodo:
            try:
                conn.execute('''
                    UPDATE oferta_disciplina
                    SET disciplina_id = ?, curso = ?, ano_frequencia = ?, semestre = ?, periodo = ?
                    WHERE id = ?
                ''', (novo_disciplina_id, novo_curso, novo_ano_frequencia, novo_semestre, novo_periodo, id))
                conn.commit()
                flash('Oferta atualizada com sucesso.', 'success')
            except sqlite3.IntegrityError:
                flash(
                    'Erro: Já existe uma oferta idêntica (Disciplina/Curso/Ano/Semestre/Período) cadastrada.', 'danger')
            except Exception as e:
                flash(f'Erro ao atualizar oferta: {str(e)}', 'danger')
        else:
            flash('Todos os campos são obrigatórios.', 'danger')

        conn.close()
        return redirect(url_for('gerenciar_oferta'))

    conn.close()
    return render_template('editar_oferta.html',
                           oferta=oferta,
                           disciplinas=disciplinas_disponiveis,
                           cursos=cursos,
                           anos=anos,
                           semestres=semestres,
                           periodos=periodos)


# Rota para Eliminar Oferta
@app.route('/oferta/excluir/<int:id>')
def excluir_oferta(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # 1. Verificar se a oferta está associada a algum professor
    associacoes_count = conn.execute(
        'SELECT COUNT(*) FROM professor_oferta WHERE oferta_id = ?', (id,)).fetchone()[0]

    if associacoes_count > 0:
        flash(
            f'Não é possível excluir a oferta. Há {associacoes_count} professor(es) associado(s) a ela. Remova as associações primeiro.', 'danger')
        conn.close()
        return redirect(url_for('gerenciar_oferta'))

    try:
        # 2. Excluir a oferta
        conn.execute('DELETE FROM oferta_disciplina WHERE id = ?', (id,))
        conn.commit()
        flash('Oferta de disciplina excluída com sucesso.', 'success')
    except Exception as e:
        flash(f'Erro ao excluir oferta: {str(e)}', 'danger')

    conn.close()
    return redirect(url_for('gerenciar_oferta'))


@app.route('/associacoes', methods=['GET'])
def listar_associacoes():
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado. Apenas o administrador pode gerenciar associações.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # 1. BUSCAR TODOS OS PROFESSORES COM SEUS CURSOS DE ATUAÇÃO (N:M)
    professores_raw = conn.execute('''
        SELECT 
            p.id, p.nome, GROUP_CONCAT(pc.curso) AS cursos_atuacao
        FROM professores p
        LEFT JOIN professor_curso pc ON p.id = pc.professor_id
        GROUP BY p.id
        ORDER BY p.nome
    ''').fetchall()
    professores = [dict(p) for p in professores_raw]

    associacoes = {}

    # Processa cada professor individualmente
    for professor in professores:
        prof_id = professor['id']
        # Converte a string GROUP_CONCAT para uma lista de cursos
        cursos_prof = professor['cursos_atuacao'].split(
            ',') if professor['cursos_atuacao'] else []
        professor['cursos_atuacao'] = professor['cursos_atuacao'] if professor['cursos_atuacao'] else None
        professor['cursos_list'] = cursos_prof

        # 2. Obter Ofertas Atuais do Professor (Para marcar os checkboxes)
        ofertas_do_prof = conn.execute("""
            SELECT 
                od.id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.semestre, od.periodo
            FROM oferta_disciplina od
            INNER JOIN professor_oferta po ON od.id = po.oferta_id
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            WHERE po.professor_id = ?
            ORDER BY od.curso, d.nome
        """, (prof_id,)).fetchall()

        # Salva a lista de associações atuais para o template
        associacoes[prof_id] = ofertas_do_prof

        # 3. FILTRAR AS OFERTAS DISPONÍVEIS (Pela especialização do Professor)

        if cursos_prof:
            # Cria a string de placeholders (?, ?, ?) para a cláusula WHERE IN
            placeholders = ','.join(['?'] * len(cursos_prof))

            ofertas_para_associar = conn.execute(f"""
                SELECT 
                    od.id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.semestre, od.periodo
                FROM oferta_disciplina od
                INNER JOIN disciplinas d ON od.disciplina_id = d.id
                WHERE od.curso IN ({placeholders})
                ORDER BY od.curso, od.ano_frequencia, od.semestre, d.nome
            """, cursos_prof).fetchall()

            professor['ofertas_para_associar'] = ofertas_para_associar
        else:
            # Se o professor não tem cursos, a lista de ofertas disponíveis é vazia
            professor['ofertas_para_associar'] = []

    conn.close()

    return render_template('gerenciar_associacoes.html',
                           professores=professores,
                           associacoes=associacoes)


@app.route('/associacoes/salvar', methods=['POST'])
def salvar_associacoes():
    if session.get('tipo_usuario') != 'Admin':
        # Retorna erro JSON diretamente
        return jsonify({'sucesso': False, 'mensagem': 'Acesso negado'}), 403

    # 1. Obter dados
    professor_id = request.form.get('professor_id')
    ofertas_selecionadas = request.form.getlist('ofertas')

    if not professor_id:
        return jsonify({'sucesso': False, 'mensagem': 'ID do professor não fornecido'}), 400

    conn = get_db_connection()  # Conexão aberta aqui

    try:
        # --- PONTO DE VALIDAÇÃO CRÍTICO: MANTEMOS A CONEXÃO ABERTA ---
        for oferta_id in ofertas_selecionadas:
            # Verifica se a oferta já está associada a OUTRO professor
            check = conn.execute('''
                SELECT professor_id 
                FROM professor_oferta 
                WHERE oferta_id = ? AND professor_id != ?
            ''', (oferta_id, professor_id)).fetchone()

            if check:
                # SE HOUVER CONFLITO, BUSCAMOS INFORMAÇÕES ADICIONAIS NA CONEXÃO ABERTA

                # 1. Busca o nome do professor conflitante
                professor_conflito = conn.execute(
                    'SELECT nome FROM professores WHERE id = ?', (check['professor_id'],)).fetchone()
                nome_prof_conflito = professor_conflito['nome'] if professor_conflito else 'Outro Professor'

                # 2. Busca o nome da disciplina
                oferta_info = conn.execute('''
                    SELECT d.nome FROM oferta_disciplina od
                    INNER JOIN disciplinas d ON od.disciplina_id = d.id
                    WHERE od.id = ?
                ''', (oferta_id,)).fetchone()
                nome_oferta = oferta_info['nome'] if oferta_info else 'Oferta Desconhecida'

                # LANÇA UMA EXCEÇÃO COM A MENSAGEM CLARA
                raise ValueError(
                    f'❌ Falha: A oferta "{nome_oferta}" já está associada ao {nome_prof_conflito}. Uma oferta só pode ter um professor.')
        # --- FIM DA VALIDAÇÃO (NENHUM CONFLITO ENCONTRADO) ---

        # 2. Apagar todas as associações existentes para este professor
        conn.execute(
            'DELETE FROM professor_oferta WHERE professor_id = ?', (professor_id,))

        # 3. Inserir as novas associações
        for oferta_id in ofertas_selecionadas:
            conn.execute('''
                INSERT INTO professor_oferta (professor_id, oferta_id)
                VALUES (?, ?)
            ''', (professor_id, oferta_id))

        conn.commit()
        return jsonify({'sucesso': True, 'mensagem': f'Associações de Ofertas ({len(ofertas_selecionadas)}) atualizadas com sucesso.'})

    except ValueError as e:
        # Captura o erro customizado de validação
        conn.rollback()
        # Retorna a mensagem clara, sem fechar o servidor
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 409

    except Exception as e:
        # Captura outros erros (ex: IntegrityError se a regra UNIQUE falhar no INSERT por fora da validação)
        conn.rollback()
        logging.error(f'Erro fatal na lógica de associação: {str(e)}')
        # Retorna 500 para erro de servidor, com uma mensagem genérica
        return jsonify({'sucesso': False, 'mensagem': f'Erro de servidor: {type(e).__name__}'}), 500

    finally:
        # A conexão SÓ é fechada aqui.
        conn.close()


@app.route('/associacoes/eliminar/<int:oferta_id>/<int:professor_id>', methods=['POST'])
def eliminar_associacao(oferta_id, professor_id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('listar_associacoes'))

    conn = get_db_connection()
    try:
        # Busca o nome da oferta e do professor para a mensagem de feedback
        oferta_nome = conn.execute('''
            SELECT d.nome FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            WHERE od.id = ?
        ''', (oferta_id,)).fetchone()

        professor_nome = conn.execute(
            'SELECT nome FROM professores WHERE id = ?', (professor_id,)).fetchone()

        # 1. Executa a exclusão na tabela M:N
        conn.execute('''
            DELETE FROM professor_oferta 
            WHERE oferta_id = ? AND professor_id = ?
        ''', (oferta_id, professor_id))
        conn.commit()

        msg = f'Associação eliminada: Oferta "{oferta_nome["nome"]}" desassociada do Professor "{professor_nome["nome"]}" com sucesso.'
        flash(msg, 'success')

    except Exception as e:
        flash(f'Erro ao eliminar associação: {str(e)}', 'danger')
        conn.rollback()

    finally:
        conn.close()

    # Redireciona de volta para a lista de associações
    return redirect(url_for('listar_associacoes'))

# Rota para obter as disciplinas por curso e ano de frequência (API)


@app.route('/api/disciplinas_por_curso_ano', methods=['GET'])
def api_disciplinas_por_curso_ano():
    # Parâmetros esperados do frontend
    curso = request.args.get('curso')
    ano_frequencia = request.args.get('ano_frequencia')
    # O período também é crucial para filtrar a oferta
    periodo = request.args.get('periodo')

    if not curso or not ano_frequencia or not periodo:
        # Retorna lista vazia se os parâmetros obrigatórios não forem fornecidos
        return jsonify([])

    conn = get_db_connection()
    try:
        # Busca todas as disciplinas/ofertas associadas ao curso, ano e período
        ofertas = conn.execute('''
            SELECT 
                od.id AS oferta_id, 
                d.nome AS nome_disciplina,
                od.semestre,
                od.periodo
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            WHERE od.curso = ? AND od.ano_frequencia = ? AND od.periodo = ?
            ORDER BY od.semestre, d.nome
        ''', (curso, ano_frequencia, periodo)).fetchall()

        # Formata o resultado para JSON
        disciplinas_list = []
        for o in ofertas:
            disciplinas_list.append({
                'oferta_id': o['oferta_id'],
                'nome_completo': f"{o['nome_disciplina']} ({o['semestre']}º Semestre - {o['periodo']})",
                'disciplina': o['nome_disciplina']
            })

        return jsonify(disciplinas_list)
    except Exception as e:
        logging.error(f"Erro ao buscar disciplinas: {e}")
        return jsonify({"erro": str(e)}), 500
    finally:
        conn.close()


@app.route('/gerenciar_credenciais_prof', methods=['GET', 'POST'])
def gerenciar_credenciais_prof():
    if session.get('tipo_usuario') != 'Admin':
        abort(403)  # Apenas Admin pode acessar

    conn = get_db_connection()

    # 1. Lógica para Criar/Atualizar
    if request.method == 'POST':
        professor_id = request.form.get('professor_id')
        usuario = request.form.get('usuario').strip()
        senha = request.form.get('senha')

        if not (professor_id and usuario and senha):
            flash('Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('gerenciar_credenciais_prof'))

        senha_hash = generate_password_hash(senha)

        try:
            # Tenta atualizar (se já existe)
            cursor = conn.execute('''
                UPDATE credenciais_professores SET usuario = ?, senha_hash = ?
                WHERE professor_id = ?
            ''', (usuario, senha_hash, professor_id))

            if cursor.rowcount == 0:
                # Se não atualizou, insere
                conn.execute('''
                    INSERT INTO credenciais_professores (professor_id, usuario, senha_hash)
                    VALUES (?, ?, ?)
                ''', (professor_id, usuario, senha_hash))
                flash('Credencial criada com sucesso!', 'success')
            else:
                flash('Credencial atualizada com sucesso!', 'success')
            conn.commit()

        except sqlite3.IntegrityError:
            flash('Erro: Este usuário ou professor já possui credenciais.', 'danger')
        except Exception as e:
            flash(f'Erro: {str(e)}', 'danger')

        return redirect(url_for('gerenciar_credenciais_prof'))

    # 2. Lógica para Listar

    # Professores SEM credenciais (para o formulário de criação)
    professores_sem_cred = conn.execute('''
        SELECT p.id, p.nome 
        FROM professores p 
        LEFT JOIN credenciais_professores cp ON p.id = cp.professor_id
        WHERE cp.professor_id IS NULL
        ORDER BY p.nome
    ''').fetchall()

    # Professores COM credenciais (para a lista de gestão)
    professores_com_cred = conn.execute('''
        SELECT p.id, p.nome, cp.usuario 
        FROM professores p 
        INNER JOIN credenciais_professores cp ON p.id = cp.professor_id
        ORDER BY p.nome
    ''').fetchall()

    conn.close()
    return render_template('gerenciar_credenciais_prof.html',
                           professores_sem_cred=professores_sem_cred,
                           professores_com_cred=professores_com_cred)


@app.route('/api/ofertas_por_professor/<int:prof_id>', methods=['GET'])
def api_ofertas_por_professor(prof_id):
    """Retorna a lista de ofertas associadas a um professor específico."""
    conn = get_db_connection()

    # Se o ID for 0, retorna todas as ofertas (usado para Admin quando nenhum professor foi selecionado)
    if prof_id == 0:
        ofertas = conn.execute('''
            SELECT 
                od.id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.semestre, od.periodo, p.nome AS nome_professor
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            INNER JOIN professor_oferta po ON od.id = po.oferta_id
            LEFT JOIN professores p ON po.professor_id = p.id
            ORDER BY od.curso, d.nome
        ''').fetchall()
    else:
        # Filtra apenas pelas ofertas do professor selecionado
        ofertas = conn.execute('''
            SELECT 
                od.id, d.nome AS nome_disciplina, od.curso, od.ano_frequencia, od.semestre, od.periodo, p.nome AS nome_professor
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            INNER JOIN professor_oferta po ON od.id = po.oferta_id
            LEFT JOIN professores p ON po.professor_id = p.id
            WHERE po.professor_id = ?
            ORDER BY od.curso, d.nome
        ''', (prof_id,)).fetchall()

    conn.close()
    # Converte os Rows do SQLite para um formato serializável (lista de dicionários)
    return jsonify([dict(o) for o in ofertas])

# Rota para Excluir Credencial (Admin)


@app.route('/credenciais_prof/excluir/<int:prof_id>')
def excluir_credencial_prof(prof_id):
    if session.get('tipo_usuario') != 'Admin':
        abort(403)

    conn = get_db_connection()
    conn.execute(
        'DELETE FROM credenciais_professores WHERE professor_id = ?', (prof_id,))
    conn.commit()
    conn.close()
    flash('Credencial excluída com sucesso.', 'success')
    return redirect(url_for('gerenciar_credenciais_prof'))


# ==============================================================================
# FUNÇÃO DE LÓGICA DE NEGÓCIO PARA PONTO (Funcionários)
# ==============================================================================

def registrar_entrada_saida_funcionario(numero_bi):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Obter ID do funcionário
    cursor.execute(
        "SELECT id, nome, funcao, departamento FROM funcionarios WHERE numero_bi = ?", (numero_bi,))
    funcionario = cursor.fetchone()
    if not funcionario:
        conn.close()
        # Retorno crítico que aciona som de erro
        return f"❌ Funcionário com BI {numero_bi} não encontrado no cadastro."

    funcionario_id = funcionario["id"]
    nome_funcionario = funcionario["nome"]
    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    hoje = datetime.now().strftime('%Y-%m-%d')

    # 2. Verificar o último registro
    cursor.execute("""
        SELECT tipo_registo, data_hora FROM registo_funcionarios 
        WHERE funcionario_id = ? 
        AND date(data_hora) = date(?)
        ORDER BY data_hora DESC 
        LIMIT 1
    """, (funcionario_id, hoje))

    ultimo_registo = cursor.fetchone()

    # 2.1. Contar o número total de ENTRADAS e SAÍDAS no dia
    cursor.execute("""
        SELECT COUNT(*) AS total FROM registo_funcionarios 
        WHERE funcionario_id = ? AND date(data_hora) = date(?) AND tipo_registo = 'ENTRADA'
    """, (funcionario_id, hoje))
    total_entradas_hoje = cursor.fetchone()['total']

    cursor.execute("""
        SELECT COUNT(*) AS total FROM registo_funcionarios 
        WHERE funcionario_id = ? AND date(data_hora) = date(?) AND tipo_registo = 'SAIDA'
    """, (funcionario_id, hoje))
    total_saidas_hoje = cursor.fetchone()['total']

    # 2.2. LÓGICA DE BLOQUEIO: Se já registrou ENTRADA e SAÍDA (1 de cada), bloqueia.
    if total_entradas_hoje >= 1 and total_saidas_hoje >= 1:
        conn.close()
        # MENSAGEM FINAL DE BLOQUEIO CLARA (Contém o texto exato desejado)
        return f"⚠️ LIMITE_ATINGIDO: Já registrou sua Entrada e Saída hoje."

    # 2.3. Determinar o NOVO TIPO (Mantido)
    if total_entradas_hoje == 0 or (ultimo_registo and ultimo_registo['tipo_registo'] == 'SAIDA'):
        novo_tipo = 'ENTRADA'
    elif total_entradas_hoje == 1 and total_saidas_hoje == 0:
        novo_tipo = 'SAIDA'
    else:
        novo_tipo = 'ENTRADA'

    # 2.4. Verificação de Duplicidade Rápida (Mantida)
    if ultimo_registo and ultimo_registo['tipo_registo'] == novo_tipo and (datetime.now() - datetime.strptime(ultimo_registo['data_hora'], '%Y-%m-%d %H:%M:%S')).total_seconds() < 60:
        conn.close()
        return f"ℹ️ REGISTO_RAPIDO: Tentativa de {novo_tipo} muito rápida."

    # 3. Inserir o novo registo (Mantido)
    cursor.execute("""
        INSERT INTO registo_funcionarios (funcionario_id, data_hora, tipo_registo) 
        VALUES (?, ?, ?)
    """, (funcionario_id, agora, novo_tipo))

    conn.commit()
    conn.close()

    # MENSAGEM DE SUCESSO (Contém o nome para fins de log, mas é limpa no front)
    return f"✅ {novo_tipo}_REGISTRADA: {nome_funcionario} registrado às {agora}."


@app.route('/processar_reconhecimento_funcionario', methods=['POST'])
def processar_reconhecimento_funcionario():
    # Permite Admin, Funcionario_Admin e NOVO Funcionario
    # <-- NOVO NÍVEL ADICIONADO AQUI
    if session.get('tipo_usuario') not in ['Admin', 'Funcionario_Admin', 'Funcionario']:
        return jsonify({"sucesso": False, "mensagem": "Acesso negado.", "tocar_som_erro": True})

    dados = request.get_json()
    imagem_base64 = dados.get('imagem', '')

    if not imagem_base64:
        return jsonify({"sucesso": False, "mensagem": "Imagem não recebida.", "tocar_som_erro": True})

    try:
        # Decodificação da imagem (Mantido o padrão anterior)
        header, encoded = imagem_base64.split(",", 1)
        imagem_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 1. IDENTIFICAR ROSTO
        # Assume que identificar_rosto retorna 'coordenadas' e 'dados' (do cache)
        resultado = identificar_rosto(
            frame, known_face_encodings, known_face_names, known_face_data, known_face_estruturas)

        if not resultado.get("sucesso"):
            # Falha no reconhecimento facial ou detecção. Som de erro.
            return jsonify({
                "sucesso": False,
                "mensagem": resultado.get("mensagem", "❌ Rosto não reconhecido ou detectado."),
                "tocar_som_erro": True
            })

        numero_bi = resultado["numero_bi"]

        # --- AJUSTE CRÍTICO PARA EXIBIÇÃO DA FOTO E DADOS ---
        # 2. BUSCAR DADOS COMPLETOS (incluindo url_imagem, funcao, departamento)
        # Sobrescreve os dados do cache com a busca direta do DB (garante a URL e campos de função)
        dados_completos = buscar_dados_funcionario(numero_bi)

        if not dados_completos:
            # Rosto reconhecido, mas BI não está cadastrado como funcionário (inconsistência)
            return jsonify({
                "sucesso": True,  # Foi reconhecido, mas falha no DB
                "mensagem": f"❌ Rosto reconhecido, mas BI {numero_bi} não encontrado no BD de funcionários.",
                # Retorna os dados do cache como fallback
                "dados": resultado["dados"],
                "dimensoes": resultado["coordenadas"],
                "tocar_som_erro": True
            })

        # 3. CHAMADA DA LÓGICA DE REGISTRO
        mensagem_registo = registrar_entrada_saida_funcionario(numero_bi)

        # 4. DETERMINAR STATUS E SOM
        status_icon = mensagem_registo.split(' ')[0]
        tocar_som_erro = status_icon in ['❌', '⚠️']

        # 5. CONSTRUIR RESPOSTA UNIFICADA
        return jsonify({
            # 'sucesso' True significa que o rosto foi reconhecido e processado
            "sucesso": True,
            "mensagem": mensagem_registo,
            # ENVIA DADOS COMPLETOS (AGORA COM 'url_imagem')
            "dados": dados_completos,
            # Crucial para o frontend desenhar o retângulo
            "dimensoes": resultado["coordenadas"],
            "tocar_som_erro": tocar_som_erro  # Crucial para o frontend reproduzir o som
        })

    except Exception as e:
        logging.error(f"Erro técnico ao registrar funcionário: {e}")
        # Erro técnico, sempre som de erro
        return jsonify({"sucesso": False, "mensagem": f"⚠️ Erro técnico: {str(e)}", "tocar_som_erro": True})


# ----------------------------------------------------------------------
# ROTAS DE GERENCIAMENTO (CRUD) DE FUNCIONÁRIOS
# ----------------------------------------------------------------------

# app.py (Novas rotas /gerenciar_funcionarios e /editar_funcionario)


# app.py (Nova Rota de API para verificação RÁPIDA de rosto)
@app.route('/verificar_rosto', methods=['POST'])
def verificar_rosto_rapido():
    """
    Verifica a presença do maior rosto em um frame. 
    Usada pelo frontend para disparar o reconhecimento automático.
    """
    dados = request.get_json()
    imagem_base64 = dados.get('imagem', '')
    if not imagem_base64:
        # Não toca som de erro, é apenas uma verificação de presença
        return jsonify({"sucesso": False, "mensagem": "Imagem não recebida."})

    try:
        # 1. DECODIFICAR E PREPARAR IMAGEM
        if ',' in imagem_base64:
            header, encoded = imagem_base64.split(",", 1)
        else:
            encoded = imagem_base64

        imagem_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Redimensiona para 1/4 (25%) para velocidade
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        # 2. DETECTAR ROSTOS (APENAS DETECÇÃO, SEM RECONHECIMENTO)
        face_locations = face_recognition.face_locations(
            rgb_small, model="cnn")  # Usa CNN para mais precisão na detecção

        if not face_locations:
            return jsonify({"sucesso": False, "mensagem": "❌ Nenhum rosto detectado."})

        # 3. IDENTIFICAR O MAIOR ROSTO
        face_areas = [(b - t) * (r - l) for t, r, b, l in face_locations]
        largest_index = int(np.argmax(face_areas))
        top, right, bottom, left = face_locations[largest_index]

        # O retorno é nas coordenadas do FRAME REDIMENSIONADO (1/4),
        # o JS multiplica por 4 para desenhar o retângulo de feedback.
        return jsonify({
            "sucesso": True,
            "dimensions": {
                "top": top,
                "right": right,
                "bottom": bottom,
                "left": left
            }
        })

    except Exception as e:
        logging.error(f"Erro na verificação rápida de rosto: {e}")
        return jsonify({"sucesso": False, "mensagem": f"Erro interno: {str(e)}"})


@app.route('/gerenciar_funcionarios', methods=['GET', 'POST'])
def gerenciar_funcionarios():
    if session.get('tipo_usuario') != 'Admin':
        flash(
            'Acesso negado. Apenas o administrador pode gerenciar funcionários.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # ----------------------------------------------------
    # Lógica de POST para REGISTRO (Mantida)
    # ----------------------------------------------------
    if request.method == 'POST':
        # Nota: As variáveis globais (known_face_encodings, etc.) necessárias para o cache
        # devem ser declaradas como 'global' se forem modificadas aqui, mas como o código
        # do POST já está configurado para retornar jsonify e o AJAX do frontend chama
        # a rota '/recarregar_rostos' separadamente, o foco aqui é a listagem.

        nome = request.form['nome']
        funcao = request.form['funcao']
        departamento = request.form['departamento']
        numero_bi = request.form['numero_bi']

        # DADOS DA FOTO (Base64 do registro)
        imagem_capturada = request.form.get('imagem_capturada')

        foto_atualizada = False

        try:
            # 1. INSERIR NO BANCO DE DADOS
            conn.execute('''
                INSERT INTO funcionarios (nome, funcao, departamento, numero_bi)
                VALUES (?, ?, ?, ?)
            ''', (nome, funcao, departamento, numero_bi))
            conn.commit()

            # 2. PROCESSAR E SALVAR FOTO
            caminho_foto = os.path.join("known_faces", f"{numero_bi}.jpg")

            if imagem_capturada:
                if ',' in imagem_capturada:
                    header, encoded = imagem_capturada.split(",", 1)
                else:
                    encoded = imagem_capturada

                imagem_bytes = base64.b64decode(encoded)
                with open(caminho_foto, "wb") as f:
                    f.write(imagem_bytes)
                foto_atualizada = True

            elif 'foto_manual' in request.files:
                arquivo = request.files['foto_manual']
                if arquivo and arquivo.filename:
                    arquivo.save(caminho_foto)
                    foto_atualizada = True

            # Retorna JSON para o Frontend fazer o recarregamento assíncrono
            return jsonify({'sucesso': True,
                            'foto_atualizada': foto_atualizada,
                            'mensagem': f'Funcionário {nome} registrado com sucesso!'})

        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'sucesso': False, 'mensagem': 'Erro: Número de BI já registrado.'}), 400
        except Exception as e:
            conn.close()
            return jsonify({'sucesso': False, 'mensagem': f'Erro ao registrar funcionário: {str(e)}'}), 500

    # ----------------------------------------------------
    # Lógica de GET para FILTRO e LISTAGEM (IMPLEMENTADA)
    # ----------------------------------------------------

    # 1. Obter Parâmetros de Filtro do URL
    termo = request.args.get('termo', '').strip()
    funcao_filtro = request.args.get('funcao', '').strip()
    departamento_filtro = request.args.get('departamento', '').strip()

    sql = 'SELECT * FROM funcionarios WHERE 1=1'
    params = []

    if termo:
        sql += ' AND (nome LIKE ? OR numero_bi LIKE ?)'
        params += [f'%{termo}%', f'%{termo}%']

    if funcao_filtro:
        sql += ' AND funcao = ?'
        params.append(funcao_filtro)

    if departamento_filtro:
        sql += ' AND departamento = ?'
        params.append(departamento_filtro)

    sql += ' ORDER BY nome'

    # 2. Busca os funcionários filtrados
    funcionarios = conn.execute(sql, tuple(params)).fetchall()

    # 3. Busca Funções e Departamentos únicos para os dropdowns de filtro
    funcoes_disponiveis = conn.execute(
        "SELECT DISTINCT funcao FROM funcionarios WHERE funcao IS NOT NULL AND funcao != '' ORDER BY funcao").fetchall()
    departamentos_disponiveis = conn.execute(
        "SELECT DISTINCT departamento FROM funcionarios WHERE departamento IS NOT NULL AND departamento != '' ORDER BY departamento").fetchall()

    conn.close()

    # 4. Renderiza o template, passando os dados necessários
    return render_template('gerenciar_funcionarios.html',
                           funcionarios=funcionarios,
                           termo=termo,
                           funcao_filtro=funcao_filtro,
                           departamento_filtro=departamento_filtro,
                           funcoes_disponiveis=funcoes_disponiveis,
                           departamentos_disponiveis=departamentos_disponiveis)
# Rota para Editar/Atualizar Funcionário


@app.route('/funcionario/<int:id>', methods=['GET', 'POST'])
def editar_funcionario(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    # 1. Busca o funcionário
    funcionario = conn.execute(
        'SELECT * FROM funcionarios WHERE id = ?', (id,)).fetchone()

    if not funcionario:
        conn.close()
        return "Funcionário não encontrado.", 404

    # Caminho da foto ANTIGA (importante para renomear/remover)
    caminho_foto_antigo = os.path.join(
        'known_faces', f"{funcionario['numero_bi']}.jpg")

    if request.method == 'POST':
        nome = request.form['nome']
        funcao = request.form['funcao']
        departamento = request.form['departamento']
        novo_numero_bi = request.form['numero_bi']

        # Base64 da foto capturada ou upload de arquivo
        nova_foto_base64 = request.form.get('nova_foto_base64_func')

        # Variáveis globais (para o cache)
        global known_face_encodings, known_face_names, known_face_data, known_face_estruturas

        foto_atualizada_no_disco = False
        bi_alterado = funcionario['numero_bi'] != novo_numero_bi

        try:
            # 1. Atualização no banco de dados
            conn.execute('''
                UPDATE funcionarios
                SET nome = ?, funcao = ?, departamento = ?, numero_bi = ?
                WHERE id = ?
            ''', (nome, funcao, departamento, novo_numero_bi, id))
            conn.commit()

            # 2. LÓGICA DE ATUALIZAÇÃO DA FOTO E CACHE
            caminho_foto_novo = os.path.join(
                'known_faces', f"{novo_numero_bi}.jpg")

            # A) Se o BI mudou, remove a foto antiga
            if bi_alterado and os.path.exists(caminho_foto_antigo):
                os.remove(caminho_foto_antigo)

            # B) Salva a nova foto se houver upload/captura
            if nova_foto_base64 or ('nova_foto_func' in request.files and request.files['nova_foto_func'].filename):
                # ...
                if nova_foto_base64:
                    try:
                        if ',' in nova_foto_base64:
                            header, encoded = nova_foto_base64.split(",", 1)
                        else:
                            encoded = nova_foto_base64

                        imagem_bytes = base64.b64decode(encoded)
                        with open(caminho_foto_novo, "wb") as f:
                            f.write(imagem_bytes)
                        foto_atualizada_no_disco = True
                    except Exception as e:
                        logging.error(
                            f"Erro ao salvar foto Base64 (Func) em edição: {e}")

                elif 'nova_foto_func' in request.files:
                    arquivo = request.files['nova_foto_func']
                    if arquivo and arquivo.filename:
                        arquivo.save(caminho_foto_novo)
                        foto_atualizada_no_disco = True

            conn.close()

            # 3. ATUALIZAÇÃO DO CACHE EM MEMÓRIA

            if bi_alterado or foto_atualizada_no_disco:
                # Remove o BI ANTIGO (se o BI mudou ou se a foto foi substituída para o mesmo BI)
                bi_para_remover = funcionario['numero_bi']
                if bi_para_remover in known_face_names:
                    idx = known_face_names.index(bi_para_remover)
                    known_face_names.pop(idx)
                    known_face_encodings.pop(idx)
                    known_face_data.pop(bi_para_remover, None)
                    known_face_estruturas.pop(bi_para_remover, None)

                # Se o BI MUDOU, e o NOVO BI estava no cache, removemos também
                if bi_alterado and novo_numero_bi in known_face_names:
                    idx = known_face_names.index(novo_numero_bi)
                    known_face_names.pop(idx)
                    known_face_encodings.pop(idx)
                    known_face_data.pop(novo_numero_bi, None)
                    known_face_estruturas.pop(novo_numero_bi, None)

                # ATENÇÃO: COMENTAMOS ESTA LINHA PARA EVITAR QUE O FLASK REINICIE
                # A GRAVAÇÃO NO DISCO AGORA É FEITA SOMENTE PELA CHAMADA AJAX /recarregar_rostos
                # from facial_utils import salvar_cache
                # salvar_cache(known_face_encodings, known_face_names, known_face_data, known_face_estruturas)

            # Retorna JSON para o Frontend (AJAX)
            return jsonify({'sucesso': True,
                            'foto_atualizada': foto_atualizada_no_disco,
                            'mensagem': f'Funcionário {nome} atualizado com sucesso. O cache será recarregado na próxima inicialização ou manualmente.'})

        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'sucesso': False, 'mensagem': 'Erro: Número de BI já registrado.'}), 400
        except Exception as e:
            conn.close()
            # Certifique-se de importar 'logging' no início do seu app.py: import logging
            logging.error(
                f"Erro inesperado ao atualizar funcionário: {e}", exc_info=True)
            return jsonify({'sucesso': False, 'mensagem': f'Erro ao atualizar funcionário: {str(e)}'}), 500

    # --- MÉTODO GET: Renderização da Página ---

    # Obtém o caminho da foto para verificar a existência
    caminho_foto = os.path.join(
        'known_faces', f"{funcionario['numero_bi']}.jpg")
    existe_foto = os.path.exists(caminho_foto)

    conn.close()

    # Passa o timestamp 'now' para o cache-busting do Jinja2
    return render_template('editar_funcionario.html',
                           funcionario=funcionario,
                           existe_foto=existe_foto,
                           now=datetime.now().timestamp())

# Rota para Excluir Funcionário


@app.route('/funcionario/excluir/<int:id>')
def excluir_funcionario(id):
    if session.get('tipo_usuario') != 'Admin':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # 1. Obter dados (BI) antes da exclusão
    funcionario = conn.execute(
        'SELECT numero_bi FROM funcionarios WHERE id = ?', (id,)).fetchone()
    if not funcionario:
        conn.close()
        flash('Funcionário não encontrado.', 'danger')
        return redirect(url_for('gerenciar_funcionarios'))

    numero_bi = funcionario['numero_bi']

    # Verificar registros de ponto antes de excluir
    reg_count = conn.execute(
        'SELECT COUNT(*) FROM registo_funcionarios WHERE funcionario_id = ?', (id,)).fetchone()[0]

    if reg_count > 0:
        conn.close()
        flash(
            f'Não é possível excluir. Há {reg_count} registro(s) de ponto associado(s).', 'danger')
        return redirect(url_for('gerenciar_funcionarios'))

    try:
        # 2. Remover da tabela funcionarios
        conn.execute('DELETE FROM funcionarios WHERE id = ?', (id,))
        # 3. Remover registros de ponto (redundante, mas bom para garantir)
        conn.execute(
            'DELETE FROM registo_funcionarios WHERE funcionario_id = ?', (id,))
        conn.commit()
        conn.close()

        # 4. REMOVER O ARQUIVO DE FOTO (Ação fora do BD)
        caminho_foto = os.path.join('known_faces', f"{numero_bi}.jpg")
        if os.path.exists(caminho_foto):
            os.remove(caminho_foto)

        flash('Funcionário excluído com sucesso.', 'success')
    except Exception as e:
        flash(f'Erro ao excluir funcionário: {str(e)}', 'danger')
        if conn:
            conn.close()  # Garante que a conexão seja fechada em caso de erro.

    return redirect(url_for('gerenciar_funcionarios'))


@app.route('/gerenciar_credenciais_func', methods=['GET'])
def gerenciar_credenciais_func():
    # Apenas o Admin e Funcionario_Admin podem gerenciar credenciais
    if session.get('tipo_usuario') not in ['Admin', 'Funcionario_Admin']:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # Funcionários COM credenciais
    funcionarios_com_cred = conn.execute('''
        SELECT 
            f.id, f.nome, cf.usuario 
        FROM funcionarios f
        INNER JOIN credenciais_funcionarios cf ON f.id = cf.funcionario_id
        ORDER BY f.nome
    ''').fetchall()

    # IDs dos funcionários que já têm credenciais
    ids_com_cred = [f['id'] for f in funcionarios_com_cred]

    # Funcionários SEM credenciais
    # Esta query filtra os funcionários que não estão na lista de IDs que já têm credenciais
    # A forma mais robusta e eficiente seria usando LEFT JOIN e WHERE cf.funcionario_id IS NULL
    funcionarios_sem_cred = conn.execute('''
        SELECT f.id, f.nome
        FROM funcionarios f
        LEFT JOIN credenciais_funcionarios cf ON f.id = cf.funcionario_id
        WHERE cf.funcionario_id IS NULL
        ORDER BY f.nome
    ''').fetchall()

    conn.close()

    return render_template('gerenciar_credenciais_func.html',
                           funcionarios_com_cred=funcionarios_com_cred,
                           funcionarios_sem_cred=funcionarios_sem_cred)


@app.route('/salvar_credencial_func', methods=['POST'])
def salvar_credencial_func():
    # Apenas o Admin e Funcionario_Admin podem gerenciar credenciais
    if session.get('tipo_usuario') not in ['Admin', 'Funcionario_Admin']:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    funcionario_id = request.form['funcionario_id']
    usuario = request.form['usuario'].strip()
    senha = request.form['senha'].strip()

    if not funcionario_id or not usuario or not senha:
        flash('Todos os campos são obrigatórios.', 'danger')
        return redirect(url_for('gerenciar_credenciais_func'))

    senha_hash = generate_password_hash(senha, method='pbkdf2:sha256')

    conn = get_db_connection()

    try:
        # 1. Verificar se a credencial já existe para este funcionário
        cursor = conn.execute(
            'SELECT * FROM credenciais_funcionarios WHERE funcionario_id = ?', (funcionario_id,)).fetchone()

        if cursor:
            # Atualiza (Redefine Senha/Usuário)
            conn.execute('''
                UPDATE credenciais_funcionarios 
                SET usuario = ?, senha_hash = ?
                WHERE funcionario_id = ?
            ''', (usuario, senha_hash, funcionario_id))
            flash(
                f'Credenciais para o funcionário ID {funcionario_id} atualizadas com sucesso.', 'success')
        else:
            # Insere (Cria nova credencial)
            conn.execute('''
                INSERT INTO credenciais_funcionarios (funcionario_id, usuario, senha_hash) 
                VALUES (?, ?, ?)
            ''', (funcionario_id, usuario, senha_hash))
            flash(
                f'Nova credencial criada para o funcionário ID {funcionario_id}.', 'success')

        conn.commit()

    except Exception as e:
        flash(f'Erro ao salvar credencial: {e}', 'danger')
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for('gerenciar_credenciais_func'))


@app.route('/excluir_credencial_func/<int:func_id>')
def excluir_credencial_func(func_id):
    # Apenas o Admin e Funcionario_Admin podem excluir credenciais
    if session.get('tipo_usuario') not in ['Admin', 'Funcionario_Admin']:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    try:
        # Encontra o nome do funcionário para a mensagem de feedback
        funcionario_nome = conn.execute(
            'SELECT f.nome FROM funcionarios f INNER JOIN credenciais_funcionarios cf ON f.id = cf.funcionario_id WHERE cf.funcionario_id = ?',
            (func_id,)
        ).fetchone()

        # Executa a exclusão da credencial
        conn.execute(
            'DELETE FROM credenciais_funcionarios WHERE funcionario_id = ?',
            (func_id,)
        )
        conn.commit()

        if funcionario_nome:
            flash(
                f'Credenciais de login para {funcionario_nome["nome"]} removidas com sucesso.', 'success')
        else:
            flash('Credenciais removidas com sucesso (Funcionário não encontrado, mas credencial apagada).', 'success')

    except Exception as e:
        flash(f'Erro ao excluir credencial: {e}', 'danger')
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for('gerenciar_credenciais_func'))

# ==============================================================================
# ROTA DE API PARA ESTATÍSTICAS MENSAIS (CHAMA stats_utils.py)
# ==============================================================================


@app.route('/api/estatisticas_mensais', methods=['GET'])
def api_estatisticas_mensais():
    if 'usuario' not in session:
        return jsonify({"sucesso": False, "mensagem": "Acesso não autorizado."}), 401

    tipo_usuario = session.get('tipo_usuario')
    entidade_id = session.get('entidade_id')

    # Parâmetros para filtros
    # 'estudantes' ou 'funcionarios'
    modulo = request.args.get('modulo', 'estudantes')
    mes = request.args.get('mes')
    ano = request.args.get('ano')

    try:
        if mes:
            mes = int(mes)
        if ano:
            ano = int(ano)
    except (ValueError, TypeError):
        mes = None
        ano = None

    conn = get_db_connection()
    try:
        # CHAMA A FUNÇÃO EXTERNA IMPORTADA
        dados_estatisticos = get_monthly_attendance_stats(
            conn, tipo_usuario, entidade_id, modulo, mes, ano)

        if "mensagem" in dados_estatisticos:
            return jsonify({"sucesso": False, "mensagem": dados_estatisticos["mensagem"]}), 403

        return jsonify({"sucesso": True, "dados": dados_estatisticos})

    except Exception as e:
        logging.error(f"Erro ao gerar estatísticas mensais: {e}")
        return jsonify({"sucesso": False, "mensagem": f"Erro interno do servidor: {str(e)}"}), 500
    finally:
        conn.close()


@app.route('/estatisticas')
def estatisticas():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    tipo_usuario = session.get('tipo_usuario')

    # Restrição: Apenas usuários com permissão de visualização (Admin, Funcionario_Admin, Professor, Funcionario)
    if tipo_usuario not in ['Admin', 'Funcionario_Admin', 'Professor', 'Funcionario']:
        flash(
            'Acesso negado. Você não tem permissão para visualizar estatísticas.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template('estatisticas.html', tipo_usuario=tipo_usuario, now=datetime.now)


# A rota /verificar_rosto_rapido (antiga) não precisa de alteração
# se ela é apenas para 'presença' e não liveness.
# Recomendo criar uma nova rota para o Liveness para não quebrar
# a dependência do face_recognition:
@app.route('/verificar_rosto_liveness', methods=['POST'])
def verificar_rosto_liveness():
    """
    Verifica a presença do maior rosto E a sua profundidade (liveness) via MediaPipe Face Mesh 3D.
    """
    dados = request.get_json()
    imagem_base64 = dados.get('imagem', '')
    if not imagem_base64:
        return jsonify({"sucesso": False, "mensagem": "Imagem não recebida."})

    try:
        # 1. DECODIFICAR E PREPARAR IMAGEM (Padrão)
        if ',' in imagem_base64:
            header, encoded = imagem_base64.split(",", 1)
        else:
            encoded = imagem_base64

        imagem_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(imagem_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 2. ANÁLISE DE LIVENESS E COORDENADAS (Chamada à nova função)
        # Passa o 'frame' no seu tamanho original.
        liveness_resultado = verificar_liveness_face_mesh(frame, face_mesh)

        if liveness_resultado["sucesso"]:
            # O retorno é nas coordenadas do FRAME ORIGINAL, pois o liveness_utils
            # não redimensiona por padrão. O frontend precisará adaptar o desenho do
            # retângulo se a rota /verificar_rosto_rapido (redimensionada por 0.25)
            # estiver sendo usada para o feedback visual.
            return jsonify({
                "sucesso": True,
                "liveness_passou": liveness_resultado["liveness_passou"],
                "mensagem": liveness_resultado["mensagem"],
                "dimensions": liveness_resultado["dimensoes"]
            })
        else:
            return jsonify({
                "sucesso": False,
                "mensagem": liveness_resultado["mensagem"]
            })

    except Exception as e:
        logging.error(f"Erro na verificação de liveness: {e}")
        return jsonify({"sucesso": False, "mensagem": f"Erro interno de liveness: {str(e)}"})


# Execução da aplicação
if __name__ == '__main__':
    # Recarrega os rostos conhecidos na inicialização (duplicação, mas mantida do original)
    known_face_encodings, known_face_names, known_face_data, known_face_estruturas = carregar_cache()
    if not known_face_encodings:
        known_face_encodings, known_face_names, known_face_data, known_face_estruturas = carregar_rostos_conhecidos_incremental()
        salvar_cache(known_face_encodings, known_face_names,
                     known_face_data, known_face_estruturas)

    # >>> REPETINDO A CORREÇÃO CRÍTICA PARA EVITAR O RESTART:
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
