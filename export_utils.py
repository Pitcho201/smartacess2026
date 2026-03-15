# Conteúdo que DEVE estar no seu arquivo export_utils.py (Substitua todo o conteúdo)
import os, io
from datetime import datetime
from flask import send_file, current_app
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import cm

def exportar_pdf(tipo, dados):
    
    # 1. Função auxiliar para tratar None e retornar STRING SIMPLES (para a maioria dos campos)
    def clean_string_data(data):
        return str(data) if data is not None else 'N/D'

    # 2. Função auxiliar para o NOME (usa Paragraph para forçar quebra de linha)
    def clean_name_for_pdf(data, font_size=7):
        text = str(data) if data is not None else 'N/D'
        style = getSampleStyleSheet()['Normal']
        style.fontSize = font_size
        style.alignment = 0 # LEFT alignment para nomes
        return Paragraph(text, style)

    buffer = io.BytesIO()
    if not dados:
        raise ValueError("A lista de dados para o relatório PDF está vazia.")

    # Margens: 2cm Esquerda e Direita. Redução da topMargin para 1.5cm (era 3cm). Largura útil = 17cm.
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=3*cm)

    styles = getSampleStyleSheet()
    elementos = [] 

    # --- 1. CABEÇALHO ---
    logo_path = os.path.join(current_app.root_path, 'static', 'img', 'logo.jpg') 
    if os.path.exists(logo_path):
        img = Image(logo_path, width=3*cm, height=3*cm)
        img.hAlign = 'CENTER'
        elementos.append(img)
        elementos.append(Spacer(1, 0.2*cm))

    # Estilo de Título Centralizado
    title_style = styles['Title']
    title_style.alignment = 1 # 1 = CENTER
    
    elementos.append(Paragraph("<b><font size=10 color='black'>MINISTÉRIO DO ENSINO SUPERIOR, CIÊNCIA, TECNOLOGIA E INOVAÇÃO</font></b>", title_style))
    elementos.append(Paragraph("<b><font size=10 color='black'>INSTITUTO SUPERIOR POLITÉCNICO DO BIÉ</font></b>", title_style))
    
    elementos.append(Spacer(1, 0.5*cm))

    # --- 2. TÍTULO DINÂMICO (Centralizado) ---
    TITULO_MAP = {
        'estudantes': "RELATÓRIO DE CADASTRO DE ESTUDANTES",
        'entradas': "RELATÓRIO DE FREQUÊNCIA DE ESTUDANTES",
        'funcionarios': "RELATÓRIO DE CADASTRO DE FUNCIONÁRIOS",
        'ponto': "RELATÓRIO DE REGISTROS DE PONTO"
    }
    titulo = TITULO_MAP.get(tipo, "Relatório Não Identificado")
    
    elementos.append(Paragraph(f"<b><font size=13>{titulo}</font></b>", title_style))
    elementos.append(Spacer(1, 0.2*cm))
    data_hora = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    elementos.append(Paragraph(f"Gerado em: {data_hora}", styles['Normal'])) 
    elementos.append(Spacer(1, 0.5*cm))
    
    # --- 3. DADOS DA TABELA ---
    
    # 3.1. CADASTRO DE ESTUDANTES (9 COLUNAS, Total 16.8cm)
    if tipo == 'estudantes':
        headers = ['Nº Estudante', 'Nome Completo', 'Nº BI', 'Curso', 'Período', 'Ano', 'Nascimento', 'Sexo', 'Estado Civil']
        linhas = [[
            clean_string_data(est.get('numero_estudante')), clean_name_for_pdf(est.get('nome')), clean_string_data(est.get('numero_bi')), 
            clean_string_data(est.get('curso')), clean_string_data(est.get('periodo')), clean_string_data(est.get('ano_frequencia')), 
            clean_string_data(est.get('data_nascimento')), clean_string_data(est.get('sexo')), clean_string_data(est.get('estado_civil'))
        ] for est in dados]
        
        # AJUSTE CRÍTICO: Estado Civil agora com 1.8cm
        col_widths = [1.8*cm, 3.6*cm, 2.1*cm, 1.5*cm, 2.0*cm, 1.0*cm, 2.0*cm, 1.0*cm, 1.8*cm] 
        # Total: 16.8 cm (mantido o máximo utilizável)

    # 3.2. REGISTROS DE ENTRADAS (6 COLUNAS, Total 16.5cm)
    elif tipo == 'entradas':
        headers = ['Data/Hora', 'Nome Completo', 'Nº BI', 'Curso', 'Disciplina', 'Professor']
        linhas = [[
            clean_string_data(e.get('data_hora')), clean_name_for_pdf(e.get('nome')), clean_string_data(e.get('numero_bi')), 
            clean_string_data(e.get('curso')), clean_string_data(e.get('nome_disciplina')), clean_string_data(e.get('nome_professor'))
        ] for e in dados]
        col_widths = [2.5*cm, 4.5*cm, 2.5*cm, 1.5*cm, 2.5*cm, 3.0*cm]

    # 3.3. CADASTRO DE FUNCIONÁRIOS (4 COLUNAS, Total 16.5cm)
    elif tipo == 'funcionarios':
        headers = ['Nome Completo', 'Nº BI', 'Função', 'Departamento']
        linhas = [[
            clean_name_for_pdf(f.get('nome')), clean_string_data(f.get('numero_bi')), 
            clean_string_data(f.get('funcao')), clean_string_data(f.get('departamento'))
        ] for f in dados]
        col_widths = [4.5*cm, 3.0*cm, 4.5*cm, 4.5*cm]

    # 3.4. REGISTROS DE PONTO (6 COLUNAS, Total 16.5cm)
    elif tipo == 'ponto':
        headers = ['Data/Hora', 'Tipo', 'Nome Completo', 'Nº BI', 'Função', 'Departamento']
        linhas = [[
            clean_string_data(r.get('data_hora')), clean_string_data(r.get('tipo_registo')), clean_name_for_pdf(r.get('nome')), clean_string_data(r.get('numero_bi')), 
            clean_string_data(r.get('funcao')), clean_string_data(r.get('departamento'))
        ] for r in dados]
        col_widths = [2.5*cm, 1.5*cm, 4.0*cm, 2.5*cm, 3.0*cm, 3.0*cm]

    else:
        headers = ['Erro']
        linhas = [['Tipo de relatório desconhecido.']]
        col_widths = None
        
    data = [headers] + linhas
    
    tabela = Table(data, repeatRows=1, colWidths=col_widths, hAlign='CENTER') 
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)), 
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7), 
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'), 
        
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8)
    ]))

    elementos.append(tabela) 
    elementos.append(Spacer(1, 1*cm)) 

    # --- 4. RODAPÉ ---
    elementos.append(Spacer(1, 1*cm))
    rodape = [
        "E-mail: ispb.bie@gmail.com     NIF: 5000308765",
        "Telefone: 922408061",
        "Cidade do Cuito-Bié, entre as ruas: Padre Fidalgo, Artur de Paiva e Francisco de Leite Cardoso"
    ]
    for linha in rodape:
        elementos.append(Paragraph(f"<font size=8 color='black'>{linha}</font>", styles['Normal']))

    doc.build(elementos)
    buffer.seek(0)
    nome_arquivo = f'{tipo}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return send_file(buffer, mimetype='application/pdf', download_name=nome_arquivo, as_attachment=True)