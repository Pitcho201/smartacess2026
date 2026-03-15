# stats_utils.py

from datetime import datetime

def get_monthly_attendance_stats(conn, tipo_usuario, entidade_id, entidade_tipo, mes=None, ano=None):
    """
    Gera estatísticas mensais de frequência, incluindo:
    1. Detalhes agrupados (por disciplina ou dia).
    2. Resumo de Maior e Menor Frequência individual.
    """
    if not mes or not ano:
        agora = datetime.now()
        mes = agora.month
        ano = agora.year

    mes_ano_filtro = f'{ano}-{int(mes):02d}'
    
    # Dicionário de retorno
    resultado = {
        "entidade": entidade_tipo.capitalize(), 
        "tipo_usuario": tipo_usuario, 
        "mes": mes, 
        "ano": ano, 
        "detalhes": [],
        "min_frequencia": None,
        "max_frequencia": None
    }


    # =======================================================
    # 1. ESTUDANTES (PROFESSOR / ADMIN)
    # =======================================================
    if entidade_tipo == 'estudantes' and tipo_usuario in ['Admin', 'Professor']:
        
        professor_where = ''
        professor_params = []
        curso_where = ''
        curso_params = []
        
        if tipo_usuario == 'Professor':
            cursos_assoc_query = conn.execute(
                'SELECT curso FROM professor_curso WHERE professor_id = ?', 
                (entidade_id,)
            ).fetchall()
            cursos_assoc = [c['curso'] for c in cursos_assoc_query]
            
            if not cursos_assoc:
                return resultado # Retorna vazio se o professor não tiver cursos

            professor_where = 'AND e.professor_id = ?'
            professor_params = [entidade_id]
            
            curso_placeholders = ','.join(['?'] * len(cursos_assoc))
            curso_where = f'AND s.curso IN ({curso_placeholders})'
            curso_params = cursos_assoc
        
        # Parâmetros unificados para todas as consultas de estudantes
        params_base = [mes_ano_filtro] + professor_params + curso_params
        
        # --- Consulta 1: Detalhes Agrupados (Gráfico) ---
        query_detalhes = f"""
            SELECT
                d.nome AS nome_disciplina, od.curso, od.ano_frequencia,
                COUNT(e.id) AS total_entradas_mes
            FROM entradas e
            INNER JOIN estudantes s ON e.estudante_id = s.id
            INNER JOIN disciplinas d ON e.disciplina_id = d.id
            INNER JOIN oferta_disciplina od ON e.disciplina_id = od.disciplina_id AND s.curso = od.curso AND s.ano_frequencia = od.ano_frequencia AND s.periodo = od.periodo
            WHERE STRFTIME('%Y-%m', e.data_hora) = ?
            {professor_where}
            {curso_where}
            GROUP BY d.nome, od.curso, od.ano_frequencia
            ORDER BY od.curso, od.ano_frequencia, d.nome
        """
        dados_detalhes = conn.execute(query_detalhes, tuple(params_base)).fetchall()
        
        resultado["detalhes"] = [{
            "metrica": "Total de Presenças",
            "disciplina": row['nome_disciplina'],
            "turma": f"{row['curso']} - {row['ano_frequencia']}",
            "valor": row['total_entradas_mes']
        } for row in dados_detalhes]

        # --- Consulta 2: Min/Max Frequência Individual ---
        query_min_max = f"""
            SELECT s.nome, s.numero_bi, COUNT(e.id) AS total_frequencia
            FROM entradas e
            INNER JOIN estudantes s ON e.estudante_id = s.id
            WHERE STRFTIME('%Y-%m', e.data_hora) = ?
            {professor_where}
            {curso_where}
            GROUP BY s.id
            HAVING total_frequencia > 0 -- Ignora alunos sem presença para o min
            ORDER BY total_frequencia ASC
        """
        dados_min_max = conn.execute(query_min_max, tuple(params_base)).fetchall()
        
        if dados_min_max:
            # O primeiro é o Mínimo (se tiver > 0)
            min_frequencia = dados_min_max[0]
            resultado["min_frequencia"] = {"nome": min_frequencia['nome'], "frequencia": min_frequencia['total_frequencia']}
            
            # O último é o Máximo
            max_frequencia = dados_min_max[-1]
            resultado["max_frequencia"] = {"nome": max_frequencia['nome'], "frequencia": max_frequencia['total_frequencia']}

        return resultado

    # =======================================================
    # 2. FUNCIONÁRIOS (ADMIN / FUNCIONARIO_ADMIN / FUNCIONARIO)
    # =======================================================
    elif entidade_tipo == 'funcionarios' and tipo_usuario in ['Admin', 'Funcionario_Admin', 'Funcionario']:
        
        funcionario_where = ''
        funcionario_params = []
        if tipo_usuario == 'Funcionario':
            funcionario_where = 'AND r.funcionario_id = ?'
            funcionario_params = [entidade_id]
            
        params_base = [mes_ano_filtro] + funcionario_params
            
        # --- Consulta 1: Detalhes Diários (Gráfico) ---
        query_detalhes = f"""
            SELECT
                STRFTIME('%d', r.data_hora) AS dia,
                r.tipo_registo,
                COUNT(r.id) AS total_registros
            FROM registo_funcionarios r
            WHERE STRFTIME('%Y-%m', r.data_hora) = ?
            {funcionario_where}
            GROUP BY 1, 2
            ORDER BY dia, r.tipo_registo
        """
        dados_detalhes = conn.execute(query_detalhes, tuple(params_base)).fetchall()
        
        dias_do_mes = {}
        for row in dados_detalhes:
            dia = int(row['dia'])
            if dia not in dias_do_mes:
                dias_do_mes[dia] = {"ENTRADA": 0, "SAIDA": 0}
            dias_do_mes[dia][row['tipo_registo']] = row['total_registros']

        labels_dias = sorted(list(dias_do_mes.keys()))
        data_entradas = [dias_do_mes[dia].get("ENTRADA", 0) for dia in labels_dias]
        data_saidas = [dias_do_mes[dia].get("SAIDA", 0) for dia in labels_dias]
        
        resultado["detalhes"] = {
            "labels_dias": [f"{dia}/{mes}" for dia in labels_dias],
            "data_entradas": data_entradas,
            "data_saidas": data_saidas
        }

        # --- Consulta 2: Min/Max Frequência Individual (Total de Registros) ---
        # Nota: Se for Funcionário comum, esta consulta será restrita apenas a ele mesmo (min=max=seus dados)
        query_min_max = f"""
            SELECT f.nome, f.numero_bi, COUNT(r.id) AS total_frequencia
            FROM registo_funcionarios r
            INNER JOIN funcionarios f ON r.funcionario_id = f.id
            WHERE STRFTIME('%Y-%m', r.data_hora) = ?
            {funcionario_where}
            GROUP BY f.id
            HAVING total_frequencia > 0
            ORDER BY total_frequencia ASC
        """
        dados_min_max = conn.execute(query_min_max, tuple(params_base)).fetchall()
        
        if dados_min_max:
            # O primeiro é o Mínimo
            min_frequencia = dados_min_max[0]
            resultado["min_frequencia"] = {"nome": min_frequencia['nome'], "frequencia": min_frequencia['total_frequencia']}
            
            # O último é o Máximo
            max_frequencia = dados_min_max[-1]
            resultado["max_frequencia"] = {"nome": max_frequencia['nome'], "frequencia": max_frequencia['total_frequencia']}

        return resultado

    return {"entidade": entidade_tipo, "tipo_usuario": tipo_usuario, "mes": mes, "ano": ano, "detalhes": [], "mensagem": "Módulo ou Permissão Inválida."}