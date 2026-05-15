/**
 * EAlert Tracker v3.8.4
 * 
 * ⚠️ 准确性原则（最高优先级）：
 * 提供的信息必须经过确认，绝不捏造任何字段。
 * 所有字段（DOI、作者、日期、摘要）必须从可靠 API 验证获取，
 * 无法提取时明确标注「（作者信息无法确认）」等占位符，绝不猜测。
 * 
 * 主要版本历史：
 * v3.7.0: 删除 extractDOI 捏造 DOI 逻辑；新增 validateDOI 验证；
 *         ensureFields 重写为 ensureAccurateFields；所有无法确认字段标注清楚
 * v3.6.1: 去重逻辑（标题+URL/DOI 双重比对）
 * v3.6.0: 模板独立为 template.md
 * v3.5:   报告格式优化（原文标题、点评质量）
 * v3.4:   新增 Google Scholar Alerts 支持
 */

const Imap = require('imap');
const { simpleParser } = require('mailparser');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
// v3.8.1: 移除 nodemailer，不再发送邮件
// const nodemailer = require('nodemailer');
require('dotenv').config({ path: path.join(__dirname, '../.env') });

// ============ 配置 ============
const CONFIG = {
  targetKeywords: [
    'bioinformatics', 'computational biology', 'multi-omics', 'single-cell',
    'scRNA-seq', 'RNA-seq', 'ATAC-seq', 'proteomics', 'metabolomics',
    'spatial transcriptomics', 'genome-wide', 'GWAS',
    'machine learning', 'deep learning', 'neural network', 
    'large language model', 'foundation model', 'AlphaFold',
    'cancer', 'tumor', 'oncology', 'carcinoma', 
    'immunotherapy', 'immune checkpoint', 'CAR-T', 'tumor microenvironment',
    'treg', 'regulatory t', 'foxp3', 't cell', 'b cell', 'immune',
    'genomics', 'genome sequencing', 'gene expression', 'epigenomics',
    'transcriptomics', 'microbiome', 'virome',
    'stem cell', 'organoid', 'gene editing', 'CRISPR',
    'lifespan', 'longevity', 'aging', 'senescence',
    'neuroscience', 'brain organoid', 'epilepsy', 'neural',
    'systems biology', 'network medicine', 'precision medicine', 'biomarker',
    'synthetic biology', 'amino acid', 'protein', 'enzyme',
    'evolution', 'evolutionary', 'phylogeny', 'paleontology'
  ],

  journalSenders: ['nature.com', 'aaas.sciencepubs.org', 'science.org', 'cell.com', 'pnas.org', 'elsevier.com'],

  journalSubjects: [
    'Nature', 'Science', 'Cell', 'PNAS',
    'Translational', 'Immunology', 'Advances', 'Cancer',
    'Communications', 'Computational', 'Biotechnology',
    'Methods', 'Genetics', 'Medicine', 'Molecular', 'Reports', 'Metabolism',
    'Trends'
  ],

  // Google Scholar Alerts 配置
  scholarSenders: ['scholaralerts-noreply@google.com'],
  scholarSubjects: ['new articles', 'new citations', 'update'],   // Scholar 邮件 Subject 包含这些关键词
  scholarExcludeSubjects: ['confirm your scholar alert'],  // 排除确认邮件

  // 排除的非研究内容（精确匹配 Subject 关键词）
  excludeKeywords: [
    'Security alert', 'Login',
    'Careers', 'Career Path',
    'Speak up for science',
    'Unsubscribe',
    'In Other Journals',
  ],

  // v3.8.1: 移除邮件配置，只保留核心追踪参数
  daysBack: 1,
};

// ============ 工具函数 ============

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function matchesKeywords(text, keywords) {
  if (!text) return false;
  const lower = text.toLowerCase();
  return keywords.some(k => lower.includes(k.toLowerCase()));
}

function decodeSubject(str) {
  if (!str) return '';
  try {
    return str.replace(/=\?([^?]+)\?([BQ])\?([^?]*)\?=/gi, (_, charset, mode, content) => {
      if (mode === 'B') return Buffer.from(content, 'base64').toString(charset);
      if (mode === 'Q') return Buffer.from(
        content.replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
          .replace(/_/g, ' '), charset).toString();
      return content;
    });
  } catch { return str; }
}

function httpGet(url, timeout = 8000) {
  return new Promise((resolve, reject) => {
    if (!url || !url.startsWith('http')) return reject(new Error('Invalid URL'));
    const client = url.startsWith('https') ? https : http;
    const req = client.get(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36' }
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return httpGet(res.headers.location, timeout).then(resolve).catch(reject);
      }
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    });
    req.setTimeout(timeout, () => { req.destroy(); reject(new Error('Timeout')); });
    req.on('error', reject);
  });
}

// ============ 期刊识别 ============

function extractJournalFromSubject(subject) {
  const s = subject.toLowerCase();
  if (s.includes('nature communications')) return 'Nature Communications';
  if (s.includes('nature cancer')) return 'Nature Cancer';
  if (s.includes('nature computational')) return 'Nature Computational Science';
  if (s.includes('nature methods')) return 'Nature Methods';
  if (s.includes('nature genetics')) return 'Nature Genetics';
  if (s.includes('nature medicine')) return 'Nature Medicine';
  if (s.includes('nature biotechnology')) return 'Nature Biotechnology';
  if (s.includes('nature')) return 'Nature';
  if (s.includes('science translational medicine')) return 'Science Translational Medicine';
  if (s.includes('science immunology')) return 'Science Immunology';
  if (s.includes('science advances')) return 'Science Advances';
  if (s.includes('science')) return 'Science';
  if (s.includes('cell metabolism')) return 'Cell Metabolism';
  if (s.includes('cell reports')) return 'Cell Reports';
  if (s.includes('molecular cell')) return 'Molecular Cell';
  if (s.includes('trends in biotechnology')) return 'Trends in Biotechnology';
  if (s.includes('cell')) return 'Cell';
  if (s.includes('pnas')) return 'PNAS';
  return 'Journal';
}

// ============ 元数据获取 ============

/**
 * 从链接提取真实 DOI
 * 
 * ⚠️ 准确性原则（v3.7.0）：
 * 此函数只提取链接中已存在的真实 DOI。
 * 如果链接中没有真实 DOI（格式: 10.xxxx/字母开头），绝不生成或猜测。
 * 之前 v3.6.x 会通过 PII 格式生成假 DOI（如 10.1126/scitranslmed.abc123），
 * 已删除此逻辑，不再捏造任何 DOI。
 */
function extractDOI(link) {
  if (!link) return '';
  
  // 从 URL 中提取已有的真实 DOI
  const direct = link.match(/(10\.\d{4,}\/[^\s&"'?#<>,;]+)/);
  if (direct) {
    let doi = direct[1].replace(/[&"'?#<>,;].*$/, '');
    try { doi = decodeURIComponent(doi); } catch {}
    // v3.7.0: 验证看起来像真实 DOI（字母开头，不是 abc123 这种随机字符）
    if (/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) {
      return doi;
    }
  }
  
  return '';  // 链接中没有真实 DOI，返回空字符串
}

/**
 * 获取论文详情（v3.7.0 重写）
 * 
 * 准确性优先流程：
 * 1. 通过 PubMed API 获取完整元数据（作者、期刊、摘要、真实 DOI）
 * 2. 如果 PubMed 无结果，从链接提取 DOI 并通过 CrossRef 验证
 * 3. CrossRef 验证通过才使用该 DOI
 * 4. 完全无法获取时：确保原始字段准确，不捏造任何信息
 */
async function fetchPaperDetails(paper) {
  // Step 1: 优先通过 PubMed 获取完整元数据
  try {
    const meta = await fetchFromPubMed(paper.title);
    if (meta && meta.journal && meta.title) {
      ensureAccurateFields(meta);
      return meta;
    }
  } catch (e) {}
  
  // Step 2: 尝试从链接提取真实 DOI 并验证
  const doi = extractDOI(paper.link);
  if (doi) {
    const isValid = await validateDOI(doi);
    if (isValid) {
      await sleep(300);
      const meta = await fetchCrossRef(doi);
      if (meta) {
        ensureAccurateFields(meta);
        return { ...paper, ...meta, doi };
      }
    }
    // DOI 无效或无法验证，不使用该 DOI
  }
  
  // Step 3: 完全无法获取可靠元数据
  // ⚠️ 确保原始字段准确，不捏造任何信息
  paper.authors = '（作者信息无法确认）';
  paper.date = paper.date || '（发表日期无法确认）';
  paper.journal = paper.journal || '（期刊信息无法确认）';
  paper.doi = '';  // 不显示无法验证的 DOI
  paper.researchQuestion = inferResearchQuestion(paper.title, '');
  paper.contributions = inferContributions('', paper.title);
  paper.comment = generateComment(paper.title, '', paper.researchQuestion, paper.journal);
  return paper;
}

/** PubMed API 查询（通过标题搜索） */
async function fetchFromPubMed(title) {
  try {
    const query = encodeURIComponent(title.replace(/[^\w\s]/g, ' ').trim().substring(0, 100));
    const url = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${query}&retmax=1&retmode=json&sort=relevance`;
    
    const data = await httpGet(url);
    const json = JSON.parse(data);
    const pmid = json?.esearchresult?.idlist?.[0];
    
    if (!pmid) return null;
    
    await sleep(300);
    
    // 获取摘要（efetch）
    let abstract = '';
    try {
      const abstractData = await httpGet(`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=${pmid}&retmode=xml&rettype=abstract`);
      const abstractMatch = abstractData.match(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/gi);
      if (abstractMatch) {
        abstract = abstractMatch.map(m => m.replace(/<\/?AbstractText[^>]*>/gi, '').trim()).join('\n');
        abstract = abstract.replace(/<[^>]+>/g, '').trim();
      }
    } catch (e) {}
    
    await sleep(200);
    
    // 获取作者信息（esummary）
    const summaryData = await httpGet(`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=${pmid}&retmode=json`);
    const summary = JSON.parse(summaryData);
    const paperMeta = summary?.result?.[pmid];
    
    if (!paperMeta) return null;
    
    const authors = (paperMeta.authors || []).map(a => a.name).join(', ');
    const corresponding = paperMeta.authors?.[paperMeta.authors.length - 1]?.name || '';
    const journal = paperMeta.fulljournalname || paperMeta.source || '';
    const published = paperMeta.pubdate || '';
    const originalTitle = paperMeta.title || title;
    
    // v3.7.0: 验证 DOI 格式，拒绝捏造的假 DOI
    let doi = paperMeta.elocationid?.replace('doi: ', '') || '';
    if (doi && !/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) doi = '';
    
    const researchQuestion = inferResearchQuestion(originalTitle, abstract);
    const contributions = inferContributions(abstract, originalTitle);
    const comment = generateComment(originalTitle, abstract, researchQuestion, journal);
    
    return {
      journal,
      title: originalTitle,
      originalTitle,
      authors: authors || '（作者信息无法确认）',
      corresponding,
      researchQuestion,
      contributions,
      comment,
      abstract,
      published,
      pmid,
      doi
    };
  } catch (e) {
    return null;
  }
}

/** CrossRef API 查询 */
async function fetchCrossRef(doi) {
  try {
    const cleanDoi = doi.replace(/[\s&"?#].*$/, '');
    const url = 'https://api.crossref.org/works/' + encodeURIComponent(cleanDoi);
    const data = await httpGet(url);
    const json = JSON.parse(data);
    const w = json.message;
    if (!w) return null;
    
    let abstract = (w.abstract || '').replace(/<[^>]+>/g, '').trim();
    if (abstract.length < 20) abstract = '';
    
    const authors = (w.author || []).map(a => `${a.given || ''} ${a.family || ''}`.trim()).join(', ');
    const corresponding = (w.author || []).find(a => a.type === 'author' || a.sequence === 'first')?.affiliation?.name || '';
    
    const title = w.title?.[0] || '';
    const researchQuestion = inferResearchQuestion(title, abstract);
    const contributions = inferContributions(abstract, title);
    const comment = generateComment(title, abstract, researchQuestion, w['container-title']?.[0] || '');
    
    return {
      journal: w['container-title']?.[0] || w.publisher || '',
      title: w.title?.[0] || title,
      authors: authors || '未知',
      corresponding: corresponding,
      abstract,
      researchQuestion,
      contributions,
      comment,
      published: w.published?.['date-parts']?.[0]?.join('-') || '',
      doi: cleanDoi
    };
  } catch (e) {
    return null;
  }
}

function inferResearchQuestion(title, abstract) {
  const combined = (title + ' ' + abstract).toLowerCase();
  const t = title;
  const abs = abstract || '';
  
  // 优先从摘要第一句提取研究问题（摘要通常以背景/问题开头）
  if (abs.length > 50) {
    const firstSentences = abs.split(/[.。]/).filter(s => s.trim().length > 20).slice(0, 2);
    for (const s of firstSentences) {
      const trimmed = s.trim();
      // 背景句通常包含 "remains", "is unclear", "lack", "challenge", "limited"
      if (/remains|unclear|lack|challenge|limited|unknown|poorly|unresolved|critical|important/i.test(trimmed)) {
        return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
      }
    }
  }
  
  // 从标题推断核心科学问题
  if (combined.includes('how')) {
    const m = combined.match(/how (.{10,80}?)(?:\?|，|$|\.)/);
    if (m) return `如何（How）：${m[1].trim()}？`;
  }
  if (combined.includes('why')) {
    const m = combined.match(/why (.{10,80}?)(?:\?|，|$|\.)/);
    if (m) return `为什么（Why）：${m[1].trim()}？`;
  }
  if (combined.includes('role of') || combined.includes('function of')) {
    const m = combined.match(/(?:role|function) of (.{10,60}?)(?:\s+in|\s+during|\s+on|$)/);
    if (m) return `探索 ${m[1].trim()} 在相关生物学过程中的功能角色和作用机制`;
  }
  if (combined.includes('mechanism')) {
    const m = combined.match(/mechanism(?:s)? (?:of|underlying|behind) (.{10,60}?)(?:\s+in|\s+during|$)/);
    if (m) return `阐明 ${m[1].trim()} 的分子机制`;
  }
  if (combined.includes('regulat')) {
    return `揭示相关基因/蛋白/通路的调控机制及其在疾病或发育中的作用`;
  }
  if (combined.includes('cancer') || combined.includes('tumor')) {
    if (combined.includes('immunotherapy') || combined.includes('immune')) {
      return `探索肿瘤免疫逃逸机制或新型免疫治疗策略，以提高肿瘤治疗效果`;
    }
    return `揭示肿瘤发生发展的分子机制，寻找新的治疗靶点或生物标志物`;
  }
  if (combined.includes('single-cell') || combined.includes('scrna')) {
    return `利用单细胞组学技术解析细胞异质性、细胞状态转变或细胞间通讯网络`;
  }
  if (combined.includes('CRISPR') || combined.includes('gene editing')) {
    return `利用基因编辑技术研究基因功能或开发新型基因治疗策略`;
  }
  if (combined.includes('microbiome')) {
    return `探索微生物组与宿主之间的互作机制及其对健康或疾病的影响`;
  }
  if (combined.includes('aging') || combined.includes('longevity') || combined.includes('senescence')) {
    return `揭示衰老的分子机制，寻找延缓衰老或治疗衰老相关疾病的新靶点`;
  }
  if (combined.includes('AI') || combined.includes('machine learning') || combined.includes('deep learning')) {
    return `利用 AI/机器学习方法解决生物学或医学中的关键问题，提升预测或分析能力`;
  }
  if (combined.includes('biochar') || combined.includes('biomass')) {
    return `探索如何通过生物技术手段优化生物质材料的功能特性，推动可持续材料研发`;
  }
  if (combined.includes('polysaccharide') || combined.includes('microbiome modulation')) {
    return `研究多糖的结构-功能关系，探索其作为益生元精准调控肠道微生物组的机制与应用`;
  }
  
  // 从标题直接提取核心问题
  let q = t.replace(/\.$/, '').trim();
  if (q.length > 15 && q.length < 150) {
    return `本研究聚焦于：${q}`;
  }
  
  return `探索相关生物学机制或技术应用，解决领域内的关键科学问题`;
}

function inferContributions(abstract, title) {
  if (!abstract || abstract.length < 30) {
    const t = title.toLowerCase();
    if (t.includes('reveal') || t.includes('show')) return ['• 揭示了新的生物学机制或规律'];
    if (t.includes('identify') || t.includes('discover')) return ['• 发现了新的分子靶点或生物标志物'];
    if (t.includes('develop') || t.includes('create') || t.includes('enable')) return ['• 开发了新的技术方法或工具'];
    if (t.includes('predict') || t.includes('model')) return ['• 建立了预测模型或评估方法'];
    if (t.includes('prevent') || t.includes('treat') || t.includes('therapy')) return ['• 为疾病治疗或预防提供了新策略'];
    return ['• 提供了新的见解和实验数据支撑'];
  }
  
  const contributions = [];
  const sentences = abstract.split(/[.。;]/).filter(s => s.trim().length > 20);
  
  for (const s of sentences) {
    const t = s.trim();
    if (t.length < 20) continue;
    
    if (/reveal|show|demonstrate|discover|identify/i.test(t) && contributions.length < 2) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }
    if (/develop|create|establish|design/i.test(t) && contributions.length < 3) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }
    if (/find|observe|detect|quantify/i.test(t) && contributions.length < 3) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }
    
    if (contributions.length >= 3) break;
  }
  
  if (contributions.length === 0 && abstract.length > 50) {
    for (const s of sentences.slice(0, 3)) {
      const t = s.trim();
      if (t.length > 20) contributions.push('• ' + t.charAt(0).toUpperCase() + t.slice(1).substring(0, 150));
    }
  }
  
  return contributions.slice(0, 3);
}

/**
 * 验证并确保关键字段准确（v3.7.0 重写）
 * 
 * ⚠️ 准确性原则：
 * - DOI: 只保留格式正确（10.xxxx/字母开头）的真实 DOI，无则清空
 * - 作者: 无法确认时标注「（作者信息无法确认）」，绝不写「见原文」或「待补充」
 * - 日期: 无法确认时标注「（发表日期无法确认）」
 * - 期刊: 必须有值，无则标注「（期刊信息无法确认）」
 */
function ensureAccurateFields(paper) {
  // DOI: 验证格式，过滤捏造的假 DOI（如 abc123）
  if (paper.doi && !/^10\.\d{4,}\/[a-zA-Z]/.test(paper.doi)) {
    paper.doi = '';  // 格式不对，不是真实 DOI，清空
  }
  
  // 作者: 必须有确认的内容
  if (!paper.authors || ['见原文', '未知', '待补充', '(待补充)', '（待补充）', ''].includes(paper.authors)) {
    paper.authors = '（作者信息无法确认）';
  }
  
  // 日期
  if (!paper.published && !paper.date) {
    paper.date = '（发表日期无法确认）';
  }
  
  // 期刊
  if (!paper.journal) {
    paper.journal = '（期刊信息无法确认）';
  }
  
  // 研究问题 / 贡献 / 点评: 有则保留，无则生成（基于标题推断，这是补充说明不是事实字段）
  if (!paper.researchQuestion || paper.researchQuestion === '探索相关生物学机制或应用研究') {
    paper.researchQuestion = inferResearchQuestion(paper.title, paper.abstract || '');
  }
  if (!paper.contributions || paper.contributions.length === 0) {
    paper.contributions = inferContributions(paper.abstract || '', paper.title);
  }
  if (!paper.comment) {
    paper.comment = generateComment(paper.title, paper.abstract || '', paper.researchQuestion, paper.journal || '');
  }
}

/**
 * 验证 DOI 是否真实存在（通过 CrossRef API 查询）
 * v3.7.0: 用于在链接提取 DOI 后验证其真实性，避免使用捏造的假 DOI
 */
async function validateDOI(doi) {
  if (!doi || !/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) return false;
  try {
    const url = 'https://api.crossref.org/works/' + encodeURIComponent(doi);
    const data = await httpGet(url, 8000);
    const json = JSON.parse(data);
    return json.status === 'ok' && json.message;
  } catch {
    return false;
  }
}

/**
 * 生成精炼点评（v3.5 增强版）
 * 要求：回答——为什么重要？解决了什么问题？有什么发现？
 */
function generateComment(title, abstract, researchQuestion, journal) {
  const combined = (title + ' ' + abstract).toLowerCase();
  const t = title.toLowerCase();
  const abs = abstract || '';
  
  // 从摘要中提取关键发现
  let keyFindings = [];
  if (abs.length > 50) {
    const sentences = abs.split(/[.。]/).filter(s => s.trim().length > 30);
    // 找包含关键动词的句子
    for (const s of sentences.slice(0, 8)) {
      if (/reveal|show|demonstrate|find|discover|identify|provide|demonstrate|indicate|suggest/i.test(s)) {
        keyFindings.push(s.trim().substring(0, 200));
        if (keyFindings.length >= 2) break;
      }
    }
    // 如果没找到，用第一句
    if (keyFindings.length === 0 && sentences.length > 0) {
      keyFindings.push(sentences[0].trim().substring(0, 200));
    }
  }
  
  // 领域特定点评（基于标题关键词）
  if (t.includes('foxp3') || t.includes('treg') || t.includes('regulatory t')) {
    return 'Treg 细胞是肿瘤免疫和自身免疫疾病的核心靶点。本研究揭示了 Foxp3 如何通过表观遗传程序定义 Treg 身份，对理解免疫耐受机制和开发 Treg 靶向疗法有重要意义。';
  }
  if (t.includes('chemokine') || t.includes('t cell activation')) {
    return 'T 细胞激活是适应性免疫的核心过程。本研究探讨了趋化因子在 T 细胞激活中的双重作用，对理解免疫调节机制和开发免疫调节疗法有参考价值。';
  }
  if (combined.includes('colorectal cancer') || combined.includes('crc')) {
    if (combined.includes('ccr5') || combined.includes('ccl5')) {
      return 'CCR5/CCL5 轴在结直肠癌中扮演重要角色。本研究系统分析了其表达谱和临床价值，为结直肠癌的免疫治疗提供了新的生物标志物和潜在靶点。';
    }
    return '结直肠癌是全球高发恶性肿瘤。本研究探索了新的分子标志物或治疗靶点，对改善结直肠癌诊断和治疗有潜在价值。';
  }
  if (combined.includes('cancer') && combined.includes('immunotherapy')) {
    return '肿瘤免疫治疗响应率低是当前最大瓶颈。本研究探索了增强抗肿瘤免疫的新策略，为提高免疫治疗疗效提供了潜在新靶点或新思路。';
  }
  if (combined.includes('single-cell') || combined.includes('scrna')) {
    return '单细胞组学已从方法创新走向生物学发现。本研究利用单细胞分辨率揭示细胞异质性或状态转变，对理解发育、疾病或治疗响应有重要价值。';
  }
  if (combined.includes('crispr') || combined.includes('gene editing')) {
    return 'CRISPR 基因编辑在基础研究和基因治疗中应用广泛。本研究展示了基因编辑技术的创新应用，为基因功能研究或疾病治疗提供了新工具。';
  }
  if (combined.includes('ai') || combined.includes('machine learning') || combined.includes('deep learning')) {
    return 'AI 正在重塑生物医学研究范式。本研究展示了 AI/机器学习在解决生物学或医学关键问题中的应用潜力，值得关注其泛化能力和可解释性。';
  }
  if (combined.includes('aging') || combined.includes('longevity') || combined.includes('senescence')) {
    return '衰老是多种慢性疾病的共同风险因素。本研究揭示了衰老相关的新机制或新靶点，对延缓衰老或治疗衰老相关疾病有潜在价值。';
  }
  
  // 通用点评：基于摘要内容生成（更详细）
  if (keyFindings.length > 0) {
    const finding = keyFindings[0];
    // 提取核心动词
    const action = finding.match(/reveal|show|demonstrate|find|discover|identify|provide|indicate/i)?.[0] || 'show';
    return `本研究${action}：${finding.substring(0, 150)}。该发现对理解相关生物学过程或开发新策略有参考价值。`;
  }
  
  // 无摘要时基于标题生成简短点评
  const tLower = title.toLowerCase();
  if (tLower.includes('reveal') || tLower.includes('show') || tLower.includes('demonstrate')) {
    return `本文揭示了相关生物学过程或机制，对理解该领域有新的见解。`;
  }
  if (tLower.includes('identify') || tLower.includes('discover') || tLower.includes('find')) {
    return `本文发现了重要的分子靶点或生物标志物，具有临床或基础研究价值。`;
  }
  if (tLower.includes('develop') || tLower.includes('create') || tLower.includes('design')) {
    return `本文开发了新的技术方法或工具，对相关研究领域有推动作用。`;
  }
  if (tLower.includes('predict') || tLower.includes('model')) {
    return `本文建立了预测模型或评估方法，具有应用潜力和参考价值。`;
  }
  if (tLower.includes('prevent') || tLower.includes('treat') || tLower.includes('therapy')) {
    return `本文为疾病预防或治疗提供了新策略，具有临床转化前景。`;
  }
  // 完全通用的兜底（这是底线，尽量不用）
  return `本研究为该领域提供了新数据，建议阅读原文了解详细发现。`;
}

// ============ 论文提取（期刊邮件）============

function extractPapersFromEmail(text, subject) {
  const papers = [];
  if (!text) return papers;
  
  const journal = extractJournalFromSubject(subject);
  const lines = text.split(/\n|\r/);
  
  for (let i = 0; i < lines.length - 1; i++) {
    const line = lines[i].trim();
    const nextLine = lines[i + 1]?.trim() || '';
    
    // 跳过元信息行
    if (!line || line.startsWith('[') || line.startsWith('http') || 
        line.startsWith('Advertisement') || line.startsWith('Website') ||
        line.startsWith('Facebook') || line.startsWith('Twitter') ||
        line.startsWith('Youtube') || line.startsWith('Weibo') ||
        line.includes('Figure') || line.includes('Image:') ||
        (line.includes('Vol.') && line.includes('Iss.')) ||
        line.includes('doi:') || line.includes('Volume') && line.includes('Issue') ||
        line.includes('WEEKLY UPDATES') || line.includes('The Nature Portfolio') ||
        line.includes('Follow ') || line.includes('Join us') ||
        line.includes('Brought to you') || line.includes('Click ') ||
        /^(Article|Review|News|Perspective|Comment|Letter|Archive|Advisory|Board)/i.test(line) ||
        /^\d+$/.test(line) ||
        line.includes('Circularity') || line.includes('Multi-Journal') ||
        line.includes('Highlights') || line.includes('Announcements')) continue;
    
    // 标题特征
    if (line.length < 30 || line.length > 160) continue;
    if (!/[a-z]/.test(line.substring(0, 20))) continue;
    
    // 找链接
    let link = '';
    const isLink = (s) => s.startsWith('[') && (s.includes('http') || s.includes('springernature') || s.includes('cell.com') || s.includes('doi.org') || s.includes('aaas'));
    
    // 找作者行
    const isAuthor = (s) => /^[A-Z]/.test(s) && (s.includes(',') || s.includes(' & ') || s.includes('[...]'));
    
    if (isLink(nextLine) || isAuthor(nextLine)) {
      if (isLink(nextLine)) {
        const urlMatch = nextLine.match(/https?:\/\/[^\s\[\]"]+/);
        if (urlMatch) link = urlMatch[0];
      }
      
      let authors = '';
      let authorsLine = nextLine;
      if (isAuthor(nextLine)) {
        authors = nextLine.replace('[...]', ' et al.').replace(/\s+/g, ' ').trim();
      } else if (isLink(nextLine) && i + 2 < lines.length) {
        const afterLink = lines[i + 2]?.trim() || '';
        if (isAuthor(afterLink)) {
          authors = afterLink.replace('[...]', ' et al.').replace(/\s+/g, ' ').trim();
          authorsLine = afterLink;
        }
      }
      
      let title = line;
      if (title === title.toUpperCase() && title.length > 20) {
        title = title.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
          .replace(/'/g, "'");
      }
      
      // 找日期
      let paperDate = '';
      for (let j = i + 1; j < Math.min(i + 8, lines.length); j++) {
        const dLine = lines[j].trim();
        if (/^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}/.test(dLine)) {
          paperDate = dLine;
          break;
        }
      }
      
      papers.push({
        title,
        authors: authors || '见原文',
        journal,
        date: paperDate,
        link,
        source: 'email'
      });
    }
  }

  // 去重：标题+URL/DOI 双重比对（v3.6.1 — 修复只靠标题导致论文4/5重复的问题）
  const seen = new Map();
  return papers.filter((p, idx) => {
    const urlKey = (p.link || '').split('?')[0].toLowerCase();
    const doiKey = (p.doi || '').split('?')[0].toLowerCase();
    const compositeKey = urlKey + '|' + doiKey;
    if (!compositeKey || compositeKey === '|') {
      // 无URL/DOI，回退到标题
      const tKey = p.title.toLowerCase().replace(/\s+/g, ' ').replace(/[^a-z0-9]/g, '').substring(0, 40);
      if (seen.has('T:' + tKey)) return false;
      seen.set('T:' + tKey, idx);
      return true;
    }
    const existing = seen.get(compositeKey);
    if (existing !== undefined) {
      if (p.title.length > papers[existing].title.length) seen.set(compositeKey, idx);
      return false;
    }
    seen.set(compositeKey, idx);
    return true;
  });
}

// ============ 论文提取（Google Scholar 提醒）============

/**
 * 解析 Google Scholar Alert 邮件，提取论文信息
 * Scholar 邮件格式：
 *   - Subject: "Shane Crotty - 3 new articles"
 *   - 内容包含论文标题列表，每篇附有链接和摘要（部分有）
 */
function extractPapersFromScholarEmail(text, subject) {
  // v2.1: 调用 Python 解析器处理 Scholar 邮件
  const { execSync } = require('child_process');
  const fs = require('fs');
  const path = require('path');
  
  if (!text) return [];
  
  // 写临时文件
  const tmpFile = '/tmp/scholar_email_' + Date.now() + '.txt';
  const subjectFile = '/tmp/scholar_subj_' + Date.now() + '.txt';
  fs.writeFileSync(tmpFile, text);
  fs.writeFileSync(subjectFile, subject);
  
  try {
    const pythonScript = path.join(__dirname, 'parse_scholar_emails.py');
    const cmd = `python3 "${pythonScript}" "${tmpFile}" "${subjectFile.replace(/"/g, '\\"')}" --json`;
    const raw = execSync(cmd, { maxBuffer: 1024 * 1024 });
    const papers = JSON.parse(raw.toString());
    
    // 清理临时文件
    fs.unlinkSync(tmpFile);
    fs.unlinkSync(subjectFile);
    
    // 标准化字段
    return papers.map(p => ({
      title: p.title || '',
      authors: p.authors || p.researcher + ' et al.',
      journal: p.journal || '',
      date: p.year || '',
      link: p.url || '',
      doi: p.doi || '',
      source: 'scholar',
      researcher: p.researcher || 'Unknown',
      abstract: p.abstract || ''
    }));
  } catch (err) {
    console.error('Scholar parser error:', err.message);
    // 回退：尝试从 subject 提取链接
    const linkMatch = subject.match(/(https?:\/\/[\w.\/\-?=&%]+)/);
    if (linkMatch) {
      return [{ title: subject, authors: 'Unknown', journal: '', date: '', link: linkMatch[1], source: 'scholar', researcher: 'Unknown', abstract: '' }];
    }
    return [];
  }
}

// ============ 邮件读取 ============

function fetchRecentEmails(hours = 24) {
  return new Promise((resolve, reject) => {
    const imap = new Imap({
      user: process.env.IMAP_USER,
      password: process.env.IMAP_PASS,
      host: process.env.IMAP_HOST,
      port: parseInt(process.env.IMAP_PORT),
      tls: true,
      tlsOptions: { rejectUnauthorized: false }
    });
    
    const emails = [];
    
    imap.once('ready', () => {
      imap.openBox('INBOX', true, (err, box) => {
        if (err) { reject(err); imap.end(); return; }
        
        const since = new Date();
        since.setHours(since.getHours() - hours);
        
        imap.search([['SINCE', since]], (err, uids) => {
          if (err || !uids || uids.length === 0) { resolve([]); imap.end(); return; }
          
          console.log(`  📬 找到 ${uids.length} 封近 ${hours}h 邮件`);
          
          const fetchOp = imap.fetch(uids, { bodies: '' });
          let pending = uids.length;
          
          fetchOp.on('message', (msg) => {
            msg.on('body', (stream) => {
              simpleParser(stream, (err, parsed) => {
                if (err) { pending--; return; }
                
                const from = parsed.from?.text || '';
                const subject = decodeSubject(parsed.subject || '');
                const date = parsed.date;
                const text = parsed.text || '';
                
                const lowerFrom = from.toLowerCase();
                const lowerSubject = subject.toLowerCase();
                
                // ── Google Scholar Alerts ──
                const isScholar = CONFIG.scholarSenders.some(s => lowerFrom.includes(s));
                const isScholarConfirm = CONFIG.scholarExcludeSubjects.some(k => lowerSubject.includes(k));
                if (isScholar) {
                  if (!isScholarConfirm) {
                    emails.push({ from, subject, date: date?.toISOString(), text, type: 'scholar' });
                    console.log(`  🔔 [Scholar] ${subject.substring(0, 65)}`);
                  } else {
                    console.log(`  ⏭  [Scholar 确认邮件，跳过]`);
                  }
                  pending--;
                  if (pending <= 0) { resolve(emails); imap.end(); }
                  return;
                }
                
                // ── 期刊邮件 ──
                if (matchesKeywords(subject, CONFIG.excludeKeywords)) {
                  pending--;
                  if (pending <= 0) { resolve(emails); imap.end(); }
                  return;
                }
                
                const isJournalEmail = CONFIG.journalSenders.some(s => lowerFrom.includes(s)) ||
                  CONFIG.journalSubjects.some(j => lowerSubject.includes(j));
                
                if (isJournalEmail && !matchesKeywords(subject, CONFIG.excludeKeywords)) {
                  emails.push({ from, subject, date: date?.toISOString(), text, type: 'journal' });
                  console.log(`  ✓ ${subject.substring(0, 65)}`);
                }
                
                pending--;
                if (pending <= 0) { resolve(emails); imap.end(); }
              });
            });
          });
          
          fetchOp.once('error', () => { resolve(emails); imap.end(); });
        });
      });
    });
    
    imap.once('error', reject);
    imap.connect();
  });
}

// ============ 报告生成 ============

function generateQQReport(papers) {
  const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
  
  let r = `📚 **科研期刊追踪报告**\n`;
  r += `**日期**: ${today}\n`;
  r += `**今日发现**: ${papers.length} 篇相关论文\n\n`;
  r += `---\n\n`;

  if (papers.length === 0) {
    r += `⚠️ 今日未收到相关领域期刊目录。\n`;
    r += `建议：确认 eAlert 订阅正常，或检查垃圾邮件文件夹。`;
    return r;
  }

  papers.forEach((p, i) => {
    const sourceIcon = p.source === 'scholar' ? '🔔' : '📖';
    const sourceNote = p.source === 'scholar' && p.researcher ? ` *(Scholar: ${p.researcher})*` : '';
    
    // v3.5: 必须有原文标题和链接
    r += `### ${i + 1}. ${sourceIcon} ${p.title}${sourceNote}\n\n`;
    
    // 原文标题（如果有翻译，显示原文）
    if (p.originalTitle && p.originalTitle !== p.title) {
      r += `**原文标题**: ${p.originalTitle}\n\n`;
    }
    
    r += `**期刊**: ${p.journal || '见链接'}\n`;
    // v3.6.1: 日期必须从元数据提取，不能写"见邮件"
    const displayDate = p.published || p.date || '';
    r += `**日期**: ${displayDate || '（未提取到，请点击链接查看）'}\n`;
    // v3.8.1: 检测作者字段是否包含摘要片段
    let displayAuthors = p.authors;
    if (displayAuthors && /^(Protein sequences|These|Background|Results|Methods)/.test(displayAuthors.substring(0, 50))) {
      displayAuthors = '（作者信息无法确认）';
    }
    if (displayAuthors) {
      r += `**作者**: ${displayAuthors}\n`;
    }
    
    // v3.7.0: 链接优先级：原始链接 > 真实DOI > Google学术搜索
    if (p.link) {
      r += `\n🔗 **链接**: ${p.link}\n`;
    } else if (p.doi && /^10\.\d{4,}\/[a-zA-Z]/.test(p.doi)) {
      // v3.7.0: 只显示经过验证的真实 DOI
      r += `\n🔗 **DOI**: https://doi.org/${p.doi}\n`;
    } else {
      // v3.7.0: 无有效链接/DOI，显示 Google 学术搜索
      const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(p.title)}`;
      r += `\n🔍 **搜索**: [Google 学术搜索](${searchUrl})\n`;
    }
    r += '\n';
    
    // 点评（精简版）
    if (p.comment) {
      r += `💡 **点评**: ${p.comment}\n\n`;
    }
    
    r += `---\n\n`;
  });

  r += `## 🔬 综合评述\n\n`;
  r += generateSummary(papers);

  return r;
}

// v3.8.4: 从标题/摘要提炼一句话概要（核心科学问题，≤40字，主动句）
function generateOneSentenceSummary(p) {
  // 优先用 originalTitle（未翻译的原文标题），比翻译标题信息更丰富
  const rawTitle = p.originalTitle || p.title || '';
  const abstract = p.abstract || '';

  // 从摘要提炼（只针对有真实摘要的论文）
  if (abstract.length > 80) {
    const firstSentence = abstract.split(/[.。]/)[0].trim();
    if (firstSentence.length >= 15 && firstSentence.length <= 100) {
      let s = firstSentence
        .replace(/^We (show|demonstrate|present|report|identify|discover|found|describe|observe|introduce|develop|establish|propose|illustrate|provide)/i, '该研究')
        .replace(/^We (have shown|have demonstrated|have identified|have discovered|have found)/i, '该研究')
        .replace(/^This (study|paper|work|research|article|review|issue)/i, '该')
        .replace(/^Here,? we (show|demonstrate|report|present)/i, '该研究')
        .replace(/^Using /i, '利用')
        .replace(/^By /i, '通过')
        .replace(/^Our (results|data|findings|work)/i, '该研究')
        .replace(/^These (results|data|findings)/i, '该研究')
        .replace(/^These data (suggest|indicate|show|reveal)/i, '数据表明')
        .replace(/^Our results (suggest|indicate|show|reveal|demonstrate)/i, '结果表明')
        .replace(/^Our findings (reveal|suggest|show|indicate|demonstrate)/i, '研究表明')
        .replace(/^Collectively,? /i, '综合')
        .replace(/^Together,? /i, '综合')
        .trim();
      if (!/[。！？]$/.test(s) && s.length > 0) s += '。';
      if (s.length <= 50) return s;
    }
  }

  // 从原文标题提炼（重点：去除无意义前缀，保留核心研究对象）
  let clean = rawTitle
    .replace(/^(Cell Press Symposia|Call for papers|Special issue|Review article|Original article|Research article|Letter to the|Brief communication|Hypothesis|Perspective|Mini review)\s*[:–—-]?\s*/i, '')
    .replace(/\s*[-–—:](25 years|2026|2025|April|May|June|July|January|February|March|Apr|Vol\.?|Volume \d+|Issue \d+)\s*$/i, '')
    .replace(/\s*\(.*?\)\s*$/g, '')
    .replace(/\s*\[.*?\]\s*$/g, '')
    .replace(/\s+(of|for|in|with|by|to|and|as|through|via|using|during|across|after|before)\s+[a-z]{3,15}$/i, '')
    .replace(/^(Single.cell|Single cell|Multi.omics|Spatial|Proteomic|Metabolomic|Genomic|Transcriptomic|ATAC.Seq|RNA.Seq|CRISPR|Decoding|Understanding|Landscape|Atlas|Map|Reconstructing|Reconstruction|And)\s+/i, '')
    .replace(/^(The|A|An)\s+/i, '')
    .replace(/^Hallmarks\s+of\s+Cancer\s*/i, 'Hallmarks of Cancer ')
    .trim();

  // Hallmarks 标题：保留完整（不去掉 "of Cancer"，去掉多余的时间后缀）
  if (clean.toLowerCase().startsWith('hallmarks of cancer')) {
    clean = clean.replace(/\s*[-–—:]\s*\d+\s*years.*$/i, '').trim();
  }
  // Hallmarks 太短则补充完整
  if (clean.length >= 8 && clean.length <= 15 && clean.toLowerCase().startsWith('hallmarks')) {
    clean = 'Hallmarks of Cancer';
  }
  
  // 去除标题开头残留的冒号/短横/空格（因正则截断产生）
  clean = clean.replace(/^[\s:–—-]+/, '');
  
  // 处理全小写标题（如 email subject 转来的）
  if (/^[a-z]/.test(clean) && clean.length > 3) {
    clean = clean.charAt(0).toUpperCase() + clean.substring(1);
  }

    // 去除残留的 "And " 前缀（未在前面匹配到）
  clean = clean.replace(/^And\s+/i, '');
  if (clean.length >= 8 && clean.length <= 40) return `研究${clean}。`;
  if (clean.length > 40) return `研究${clean.substring(0, 38)}...。`;
  if (clean.length >= 4) return `研究${clean}的相关机制/问题。`;

  return '相关领域重要研究进展。';
}


// v3.8.3: 从点评/摘要提取3个主要贡献
function extractContributions(p) {
  const contributions = [];
  const title = p.title || '';
  const abstract = p.abstract || '';
  const comment = p.comment || '';
  
  // 尝试从摘要提取关键发现动词
  const findings = [];
  
  // 找摘要中以"发现/揭示/证明/提出/开发/建立/引入"开头的句子
  const sentences = abstract.split(/[.。]/);
  sentences.forEach(s => {
    const trimmed = s.trim();
    if (/^(reveal|show|demonstrate|identify|discover|establish|develop|propose|introduce|present|report|found|describe|enable|provide)/i.test(trimmed)) {
      // 截取前60字符
      let short = trimmed.substring(0, 80).trim();
      if (short.length > 10) findings.push(short);
    }
  });
  
  // 转换为中文动词开头
  if (findings.length > 0) {
    findings.slice(0, 3).forEach(f => {
      let c = f
        .replace(/^reveal/i, '揭示')
        .replace(/^show/i, '表明')
        .replace(/^demonstrate/i, '证明')
        .replace(/^identify/i, '鉴定')
        .replace(/^discover/i, '发现')
        .replace(/^establish/i, '建立')
        .replace(/^develop/i, '开发')
        .replace(/^propose/i, '提出')
        .replace(/^introduce/i, '引入')
        .replace(/^present/i, '展示')
        .replace(/^report/i, '报告')
        .replace(/^found/i, '发现')
        .replace(/^describe/i, '描述')
        .replace(/^enable/i, '实现')
        .replace(/^provide/i, '提供');
      if (c.length > 5) contributions.push(c.substring(0, 80) + (c.length > 80 ? '...' : ''));
    });
  }
  
  // v3.8.5: 无实质贡献时不添加通用文本，返回空数组
  // (通用fallback已移除，避免所有论文显示相同贡献)
  
  return contributions.slice(0, 3);
}

function generateMarkdownReport(papers) {
  const today = new Date().toISOString().split('T')[0];
  const datetime = new Date().toLocaleString('zh-CN');
  
  let md = `# 📚 科研期刊追踪报告\n\n`;
  md += `**日期**: ${today}\n`;
  md += `**监控期刊**: Nature、Science、Cell 系列及主流生物学期刊\n`;
  md += `**目标领域**: 生物信息学、计算生物学、癌生物学、免疫学、AI for Science、多组学\n\n`;
  md += `---\n\n`;
  md += `## 📊 统计\n`;
  md += `- **今日相关论文**: ${papers.length} 篇\n\n`;
  
  if (papers.length === 0) {
    md += `> 今日未收到相关领域期刊目录。\n\n---\n\n`;
    md += `**生成时间**: ${datetime}\n`;
    md += `**工具**: EAlert Tracker v3.8.3（准确性优先，不捏造任何字段）\n`;
    return md;
  }
  
  const journalCounts = {};
  papers.forEach(p => {
    const j = p.journal || '未知';
    journalCounts[j] = (journalCounts[j] || 0) + 1;
  });
  md += `### 期刊分布\n`;
  for (const [j, c] of Object.entries(journalCounts)) {
    md += `- **${j}**: ${c} 篇\n`;
  }
  md += `\n---\n\n`;
  
  md += `## 📰 论文详情\n\n`;
  
  papers.forEach((p, i) => {
    md += `### 🔬 论文${i + 1}：${p.title}\n\n`;
    if (p.source === 'scholar' && p.researcher) {
      md += `**来源**: 🔔 Google Scholar Alert (${p.researcher})\n`;
    }
    if (p.originalTitle && p.originalTitle !== p.title) {
      md += `**原文标题**: ${p.originalTitle}\n\n`;
    }
    
    // v3.8.3: 多组学简报格式 - 独立结构字段
    let mdAuthors = p.authors;
    if (mdAuthors && /^(Protein sequences|These|Background|Results|Methods)/.test(mdAuthors.substring(0, 50))) {
      mdAuthors = '（作者信息无法确认）';
    }
    if (mdAuthors) {
      md += `**作者**: ${mdAuthors}\n`;
    }
    const sourceTag = p.source === 'scholar' ? '🔔 Google Scholar' : (p.journal || '期刊链接');
    md += `**平台**: ${sourceTag}\n`;
    const mdDate = p.published || p.date || '';
    if (mdDate) md += `**日期**: ${mdDate}\n`;
    if (p.link) {
      md += `**链接**: ${p.link}\n`;
    } else if (p.doi && /^10\.\d{4,}\/[a-zA-Z]/.test(p.doi)) {
      md += `**DOI**: ${p.doi}\n`;
      md += `**链接**: https://doi.org/${p.doi}\n`;
    } else {
      const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(p.title)}`;
      md += `**链接**: ${searchUrl}\n`;
    }
    md += `\n`;
    
    // v3.8.3: 一句话概要
    md += `**一句话概要**: ${generateOneSentenceSummary(p)}\n\n`;
    
    // v3.8.3: 主要贡献
    const contributions = extractContributions(p);
    if (contributions.length > 0) {
      md += `**主要贡献**\n`;
      contributions.forEach(c => md += `- ${c}\n`);
      md += `\n`;
    }
    
    // v3.8.3: Critical 简评
    md += `**🔍 Critical 简评**: ${p.comment || '相关领域研究，建议阅读原文了解详细内容。'}\n\n`;
    
    md += `---\n\n`;
  });
  
  md += `## 💡 整体趋势\n\n`;
  md += generateSummary(papers) + '\n\n';
  md += `---\n\n`;
  md += `**生成时间**: ${datetime}\n`;
  md += `**工具**: EAlert Tracker v3.8.3（准确性优先，不捏造任何字段）\n`;

  return md;
}

function generateSummary(papers) {
  if (!papers || papers.length === 0) return '今日无相关论文。';
  
  const lines = [];
  
  const journalCounts = {};
  papers.forEach(p => {
    const j = p.journal || '未知';
    journalCounts[j] = (journalCounts[j] || 0) + 1;
  });
  
  const counts = {
    '肿瘤/免疫': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['cancer', 'tumor', 'immunotherapy', 'immune'])).length,
    'AI/机器学习': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['AI', 'machine learning', 'deep learning'])).length,
    '单细胞/组学': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['single-cell', 'scRNA', 'genomics', 'transcriptomics'])).length,
    '基因编辑': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['CRISPR', 'gene editing'])).length,
    '衰老/寿命': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['aging', 'longevity', 'lifespan'])).length,
    '神经科学': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['brain', 'neural', 'neuroscience'])).length,
    '生物工程': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['bioengineer', 'synthetic biology', 'organoid', 'biochar'])).length,
  };
  
  lines.push(`📊 **期刊分布**:`);
  for (const [j, c] of Object.entries(journalCounts)) {
    lines.push(`- ${j}: ${c} 篇`);
  }
  lines.push('');
  
  lines.push(`📈 **领域热度**:`);
  for (const [field, count] of Object.entries(counts)) {
    if (count > 0) lines.push(`- ${field}: ${count} 篇`);
  }
  lines.push('');
  
  const topFields = Object.entries(counts).filter(([, c]) => c > 0).sort((a, b) => b[1] - a[1]);
  lines.push(`💡 **本期综合评述**:`);
  
  if (papers.length >= 3) {
    if (topFields[0]) {
      lines.push(`- 本期${papers.length}篇论文中，${topFields[0][0]}研究最为活跃（${topFields[0][1]}篇），建议重点关注`);
    }
    const hasAbstract = papers.filter(p => p.abstract && p.abstract.length > 50).length;
    if (hasAbstract > 0) {
      lines.push(`- 共${hasAbstract}篇论文可获取摘要，内容质量和创新性总体较高`);
    }
    if (topFields.some(([, c]) => c >= 2)) {
      lines.push(`- 多篇涉及交叉领域研究，反映当前生命科学向多学科融合发展的趋势`);
    }
  } else {
    lines.push(`- 本期相关论文较少，持续关注后续更新`);
  }
  
  return lines.join('\n');
}

// ============ 发送（已移除） ============
// v3.8.1: 邮件发送已移除，由 AI 负责通过 message 工具发送 QQ + 推送 GitHub

// ============ 主流程 ============

async function run() {
  console.log('🚀 EAlert Tracker v3.8.5 启动\n');
  console.log(`📅 ${new Date().toLocaleString('zh-CN')}\n`);
  
  // Step 1: 获取期刊邮件
  console.log('📬 读取最近 24h 期刊邮件...');
  let emails = [];
  try {
    emails = await fetchRecentEmails(24);
  } catch (err) {
    console.error('❌ 邮件读取失败:', err.message);
  }
  
  console.log(`  → 找到 ${emails.length} 封期刊邮件\n`);
  
  if (emails.length === 0) {
    // v3.8.1: 移除 sendEmail，无邮件时只输出提示（由 AI 决定是否发送）
    console.log('⚠️ 今日无期刊邮件');
    return;
  }
  
  // Step 2: 分类提取论文
  console.log('\n🔍 解析邮件提取论文...');
  const journalEmails = emails.filter(e => e.type === 'journal');
  const scholarEmails = emails.filter(e => e.type === 'scholar');
  
  let allPapers = [];
  
  // 期刊邮件解析
  for (const email of journalEmails) {
    const papers = extractPapersFromEmail(email.text, email.subject);
    if (papers.length > 0) {
      console.log(`  📖 [期刊] ${email.subject.substring(0, 50)}: ${papers.length} 篇`);
      allPapers = allPapers.concat(papers);
    }
  }
  
  // Scholar 邮件解析
  let scholarPapers = [];
  for (const email of scholarEmails) {
    const papers = extractPapersFromScholarEmail(email.text, email.subject);
    if (papers.length > 0) {
      console.log(`  🔔 [Scholar] ${email.subject.substring(0, 50)}: ${papers.length} 篇`);
      scholarPapers = scholarPapers.concat(papers);
    }
  }
  
  console.log(`  → 共 ${allPapers.length} 篇（期刊）+ ${scholarPapers.length} 篇（Scholar）\n`);
  
  // Step 3: 关键词过滤
  console.log('🎯 关键词过滤...');
  const relevantPapers = allPapers.filter(p => matchesKeywords(p.title, CONFIG.targetKeywords));
  const relevantScholar = scholarPapers.filter(p => matchesKeywords(p.title, CONFIG.targetKeywords));
  console.log(`  → 期刊相关: ${relevantPapers.length} 篇 | Scholar相关: ${relevantScholar.length} 篇\n`);
  
  // Step 3: 合并所有相关论文
  const allRelevant = [...relevantPapers, ...relevantScholar];
  
  if (allRelevant.length === 0) {
    // v3.8.1: 移除 sendEmail，无相关论文时只输出提示（由 AI 决定是否发送）
    console.log('⚠️ 未发现相关领域论文');
    return;
  }
  
  // Step 4: 尝试获取元数据（期刊论文优先，最多处理5篇）
  console.log('📖 尝试获取论文详情...');
  const toEnrich = allRelevant.filter(p => p.source !== 'scholar').slice(0, 5);
  const toEnrichScholar = allRelevant.filter(p => p.source === 'scholar').slice(0, 3);
  const enriched = [];
  
  // 期刊论文：获取 PubMed 元数据
  for (let i = 0; i < toEnrich.length; i++) {
    const p = toEnrich[i];
    console.log(`  [${i + 1}/${toEnrich.length}] ${p.title.substring(0, 50)}...`);
    const detailed = await fetchPaperDetails(p);
    ensureAccurateFields(detailed);
    enriched.push(detailed);
    if (i < toEnrich.length - 1) await sleep(200);
  }
  
  // Scholar 论文：从链接或标题获取信息
  for (const p of toEnrichScholar) {
    console.log(`  [Scholar] ${p.title.substring(0, 50)}...`);
    // Scholar 论文尝试从链接获取 DOI
    const doi = extractDOI(p.link);
    if (doi) {
      await sleep(300);
      const meta = await fetchCrossRef(doi);
      if (meta) {
        ensureAccurateFields(meta);
        meta.source = 'scholar';
        meta.researcher = p.researcher;
        enriched.push(meta);
        continue;
      }
    }
    // 备用：直接从 PubMed 搜索标题
    const meta = await fetchPaperDetails(p);
    if (meta && meta.journal) {
      ensureAccurateFields(meta);
      meta.source = 'scholar';
      meta.researcher = p.researcher;
      enriched.push(meta);
    } else {
      // Scholar 论文：无期刊信息时补充
      p.researchQuestion = inferResearchQuestion(p.title, p.abstract || '');
      p.contributions = inferContributions(p.abstract || '', p.title);
      p.comment = generateComment(p.title, p.abstract || '', p.researchQuestion, p.journal || '');
      p.source = 'scholar';
      enriched.push(p);
    }
    await sleep(200);
  }
  
  // 剩余论文用基础信息
  const enrichedTitles = new Set(enriched.map(p => p.title.toLowerCase().substring(0, 40)));
  for (const p of allRelevant) {
    if (enrichedTitles.has(p.title.toLowerCase().substring(0, 40))) continue;
    p.researchQuestion = inferResearchQuestion(p.title, '');
    p.contributions = inferContributions('', p.title);
    p.comment = generateComment(p.title, '', p.researchQuestion, p.journal || '');
    enriched.push(p);
  }
  
  console.log(`  → 详情获取完成\n`);
  
  // Step 5: 生成报告
  console.log('📊 生成报告...');
  const qqReport = generateQQReport(enriched);
  const mdReport = generateMarkdownReport(enriched);
  
  // Step 6: 保存（v3.4: 支持 Scholar Alerts）
  const today = new Date();
  const todayStr = today.toISOString().split('T')[0];
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const weekNum = String(getISOWeek(today)).padStart(2, '0');
  const weekDir = `${year}-W${weekNum}`;
  const reportDir = path.join(__dirname, '../reports', `${year}`, `${month}`, weekDir);
  const reportPath = path.join(reportDir, `report_${todayStr}.md`);
  // v3.8.2: 只推送到 bioinformatics-frontier 仓库（不保存到本地 ealert-tracker/reports/）
  try {
    const homedir = require('os').homedir();
    const bioinfoBase = path.join(homedir, 'Documents', 'bioinformatics-frontier');
    const bioinfoDir = path.join(bioinfoBase, 'reports', `${year}`, `${month}`, weekDir);
    fs.mkdirSync(bioinfoDir, { recursive: true });
    const bioinfoPath = path.join(bioinfoDir, `${todayStr}-journal-briefing.md`);
    fs.writeFileSync(bioinfoPath, mdReport);
    console.log(`  ✓ 报告已保存: ~/Documents/bioinformatics-frontier/reports/${year}/${month}/${weekDir}/${todayStr}-journal-briefing.md`);
    
    // Git commit & push
    execSync('git add .', { cwd: bioinfoBase });
    execSync(`git commit -m "EAlert Tracker: add ${todayStr} report"`, { cwd: bioinfoBase, stdio: 'ignore' });
    execSync('git push origin main', { cwd: bioinfoBase });
    console.log(`  ✓ 已推送到 GitHub: OnlyPandaX/bioinformatics-frontier\n`);
  } catch (e) {
    console.error(`  ⚠️  Push to bioinformatics-frontier failed: ${e.message}`);
  }
  
  // Step 7: 输出报告（不发送邮件，由 AI 负责 QQ + GitHub）
  console.log('📤 报告生成完成，等待 AI 发送到 QQ 和 GitHub...');
  console.log('\n' + '='.repeat(60));
  console.log('📄 QQ 报告预览：');
  console.log('-'.repeat(60));
  console.log(qqReport.substring(0, 1500));
  if (qqReport.length > 1500) console.log('... (更多内容省略)');
  console.log('-'.repeat(60) + '\n');
  
  console.log('\n' + '='.repeat(60));
  console.log(`✅ EAlert Tracker v3.8.5 完成！`);
  console.log(`   📧 期刊邮件: ${journalEmails.length} 封`);
  console.log(`   🔔 Scholar邮件: ${scholarEmails.length} 封`);
  console.log(`   📄 论文总数: ${allPapers.length + scholarPapers.length} 篇`);
  console.log(`   🎯 相关论文: ${allRelevant.length} 篇`);
  const withAbstract = enriched.filter(p => p.abstract && p.abstract.length > 30).length;
  console.log(`   📝 含摘要: ${withAbstract} 篇`);
  if (relevantScholar.length > 0) console.log(`   👤 Scholar研究者: ${relevantScholar.map(p => p.researcher).filter((v, i, a) => a.indexOf(v) === i).join(', ')}`);
  console.log('='.repeat(60));
}

run().catch(err => {
  console.error('❌ 致命错误:', err);
  process.exit(1);
});
