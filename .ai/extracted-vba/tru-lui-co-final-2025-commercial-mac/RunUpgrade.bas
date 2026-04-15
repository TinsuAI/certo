Option Explicit
Sub runUpgradeLVC()
Dim lastRowW As Integer, lastRowT As Integer, lastRowXK As Double, lastRowDM As Long, lastRowSave As Double
Dim wsXK As Worksheet, wsDM As Worksheet, wsSave As Worksheet
Dim dictXK As Object, dictXKcot17 As Object, dictDM As Object, dictDMcot2 As Object, dictSave As Object, dictSave2 As Object
Dim arrXK As Variant, arrDM As Variant, arrSave As Variant
Dim i As Double
Dim colCountXK As Integer, colCountDM As Integer, colCountSave As Integer
Call unProtected

With ThisWorkbook.Sheets("LVC")
lastRowW = .Cells(.Rows.Count, "W").End(xlUp).row

    ' dat ten sheet
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsSave = ThisWorkbook.Sheets("Save")
    
    ' khoi tao dict
    Set dictXK = CreateObject("Scripting.Dictionary")
    Set dictXKcot17 = CreateObject("Scripting.Dictionary")
    Set dictDM = CreateObject("Scripting.Dictionary")
    Set dictDMcot2 = CreateObject("Scripting.Dictionary")
    Set dictSave = CreateObject("Scripting.Dictionary")
    Set dictSave2 = CreateObject("Scripting.Dictionary")
    
    
    
    'ḍng cuôi
    lastRowXK = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "B").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row
    
    ' khoi tao mang
    arrXK = wsXK.Range("A11:BB" & lastRowXK)
    arrDM = wsDM.Range("A7:Y" & lastRowDM)
    arrSave = wsSave.Range("A2:W" & lastRowSave)
    
    ' sô côt trong mang
    colCountXK = UBound(arrXK, 2)
    colCountDM = UBound(arrDM, 2)
    colCountSave = UBound(arrSave, 2)
    
'cài dat thoi han su dung
    Dim hanchot As Date
        hanchot = DateSerial(2026, 12, 31)
            If Now() > hanchot Then
                MsgBox "Qua han su dung " & CStr(hanchot)
                ThisWorkbook.Close SaveChanges:=False
            End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path
    sFileName = "LVC" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        
'I. dien du lieu header
    ' 1.1 gán data vào dictXK
    Dim arrRow As Variant ' tao mang tam dê chua ḍng
    Dim j As Double
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRow(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRow(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXK(arrXK(i, 2)) = arrRow ' ' Dùng côt 2 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
           
    '1.2 ghi data tu dictXK vào bang ke LVC
    Dim key As Variant
    key = Range("Q9").Value
    If dictXK.Exists(key) Then
        .Range("P6") = dictXK(key)(11) ' ty gia
        .Range("O8") = dictXK(key)(18) ' incoterm
    End If

    '1.3 t́m côt P10
    Dim total As Double
    total = 0
    For i = 1 To UBound(arrXK, 1)
        If arrXK(i, 2) = key Then
            If IsNumeric(arrXK(i, 31)) Then ' trap lôi
                total = total + arrXK(i, 31) ' tong tg nguyên tê
            End If
        End If
    Next i
    .Range("P10") = total
 
 ' II dien phân body bên trong bang kê
 ' khoi tao dict moi côt 17 là key xxxxxxxxxxxxxxxxx
 Dim arrRowcot17 As Variant ' tao mang tam dê chua ḍng
 Dim key2 As Variant
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRowcot17(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRowcot17(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXKcot17(CStr(arrXK(i, 17))) = arrRowcot17 ' ' Dùng côt 16 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
    
' tim so luong dong ma dinh muc sp
  ' khoi tao dictDM yyyyyyyyyyyyyyyyy
        Dim counifDM As Integer
        Dim keyDM As Variant
        For i = 1 To UBound(arrDM, 1)
            dictDM(CStr(arrDM(i, 1))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
    
  ' khoi tao dictDMcot2 moi de vlookup zzzzzzzzzzzzzzzzzzzzzzzzz
      Dim keyDM2 As Variant
      Dim stt As Integer
        For i = 1 To UBound(arrDM, 1)
            dictDMcot2(CStr(arrDM(i, 2))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
        
   ' khoi tao dictSave moi de vlookup wwwwwwwwwwwwwwwwwwwwww
        Dim keySave As Variant
        Dim arrsaveW As Variant
            For i = 1 To UBound(arrSave, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
              ReDim arrsaveW(1 To colCountSave) ' câp lai mang 1 chieu kích thuoc là sô côt w= 23
                For j = 1 To colCountSave
                  arrsaveW(j) = arrSave(i, j) 'Lây giá tri  ḍng i, côt j cua arrSave, gán vào vi trí j trong mang arrRow."
                Next j
                dictSave(CStr(arrSave(i, 23))) = arrsaveW ' Dùng côt 23 làm Key, và gán toàn bô ḍng & côt vào Value
            Next i
            
     'khoi tao dict de tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@
        Dim dictTong As Object, dictDem As Object
        Dim k As Long
        Dim keyTBC As String
        Dim donGia As Double
        Dim donGiaTBC As Double
        Set dictTong = CreateObject("Scripting.Dictionary")
        Set dictDem = CreateObject("Scripting.Dictionary")
        
            For k = 1 To UBound(arrSave, 1) ' duyet mang
                keyTBC = arrSave(k, 23) ' lây giá tri ḍng i côt 23 gán vào keyTBC
                If IsNumeric(arrSave(k, 9)) Then
                    donGia = arrSave(k, 9) 'lây don giá ḍng i côt 9 gán vào don giá
                    If dictTong.Exists(keyTBC) Then ' néu key tôn tai trong dict
                        dictTong(keyTBC) = dictTong(keyTBC) + donGia
                        dictDem(keyTBC) = dictDem(keyTBC) + 1
                    Else ' nguoc lai, nêu key ko tôn tai
                        dictTong.Add keyTBC, donGia ' lay don giá
                        dictDem.Add keyTBC, 1 ' sô lân xuât hien don giá = 1
                    End If
                 End If
            Next k
       
       ' khoi tao dictSave2 moi de vlookup #########################
       Dim arrSave2 As Variant
       Dim keySave2 As String
       Dim boxkeyValue As Collection 'trong Dictionary chi chua 1 giá tri duy nhât (không duoc trùng key), nên muôn luu nhiêu ḍng cho cùng 1 key, phai gom nhiêu ḍng vào 1 Collection
       For i = 1 To UBound(arrSave, 1) ' duyêt mang tu save de luu giá tri vào dictsave2
       keySave2 = CStr(arrSave(i, 23))
            arrSave2 = Array(arrSave(i, 1), arrSave(i, 2), arrSave(i, 4), arrSave(i, 14), arrSave(i, 15)) 'ghi côt 1,2,4,14,15
            If Not dictSave2.Exists(keySave2) Then ' nêu key ko tôn tai trong dict
                Set boxkeyValue = New Collection ' tao bo suu tâp chua data cua các key trùng nhau
                boxkeyValue.Add arrSave2 ' boxkey giông nhu là 1 mang trung gian
                dictSave2.Add keySave2, boxkeyValue ' ghi data t? boxkeyvalue vào dictsave2
            Else
                dictSave2(keySave2).Add arrSave2 ' nêu ko trung th́ ko cân boxkey, ghi truc tiep mang arrsave2 và dictsave2
            End If
       Next i
       

' bat dau vong lap chinh dien phan body/////////////////
        Dim so As Integer
        so = 1
    For i = 16 To lastRowW ' ****** cot moc vong lap de xuat file excel
        ThisWorkbook.Sheets("LVC").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & i) ' mă SP vao ô P7 xxxxxxxxxxxxxxxxxxxxxxxxxx
        '.Range("Q10") = .Range("W" & i) ' mă SP vao ô P7
        key2 = CStr(.Range("V" & i))
        If dictXKcot17.Exists(key2) Then
            .Range("K7") = dictXKcot17(key2)(23) 'tên sp
            .Range("K8") = Left(dictXKcot17(key2)(22), 6) 'HS code
            .Range("P8") = dictXKcot17(key2)(25) 'don giá
            .Range("L9") = dictXKcot17(key2)(28) 'dvt
            .Range("K9") = dictXKcot17(key2)(27) 'sl
            .Range("P9") = dictXKcot17(key2)(27) 'sl
            .Range("L10") = "USD"
            .Range("L11") = "USD"
            .Range("K10") = .Range("P8") * .Range("P9") ' tri gia tkx
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
        End If
        
  'tính countif  t́m sl ḍng dm yyyyyyyyyyyyyyyyyy
        keyDM = CStr(.Range("P7"))
        counifDM = 0
        For j = 1 To UBound(arrDM, 1)
            If arrDM(j, 1) = keyDM Then
                counifDM = counifDM + 1
            End If
        Next j
        .Range("P5") = counifDM ' gán sl vào dong cuoi o cot T
        .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
    
 'chay vong lap dien gia tri trong table zzzzzzzzzzzzzzzzzzz
        stt = 0
        lastRowT = .Cells(.Rows.Count, "T").End(xlUp).row
            For j = 16 To lastRowT
                 stt = stt + 1
                .Range("A" & j) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
                ' dien cot E(dm) và cot P mă NVL
                keyDM2 = CStr(stt & .Range("P7"))
                If dictDMcot2.Exists(keyDM2) Then
                    .Range("E" & j) = dictDMcot2(keyDM2)(3) ' dm
                    .Range("P" & j) = "'" & dictDMcot2(keyDM2)(2) 'mă nvl
                    .Range("F" & j) = .Range("E" & j) * .Range("P9") ' tinh sl
                    .Range("Q" & j) = "'" & .Range("Q9") & .Range("P" & j) ' tao cot phu
                End If
                
                ' dien các côt B,C,D,J,R,S wwwwwwwwwwwwwwwwwwwwwwww
                keySave = .Range("Q" & j)
                If dictSave.Exists(keySave) Then
                    .Range("B" & j) = dictSave(keySave)(7) ' tên nvl
                    .Range("C" & j) = Left(dictSave(keySave)(6), 6) ' HS code
                    .Range("D" & j) = dictSave(keySave)(12) ' dvt
                    .Range("J" & j) = dictSave(keySave)(8) ' xuât xu
                    .Range("R" & j) = dictSave(keySave)(16) ' ty giá
                    .Range("S" & j) = dictSave(keySave)(3) ' loai h́nh
                End If
                
                
                'tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
                If dictTong.Exists(keySave) Then
                    donGiaTBC = dictTong(keySave) / dictDem(keySave)
                    .Range("G" & j) = donGiaTBC ' tính trung b́nh công côt G
                End If
                
                '  tinh tri giá trong nuoc & ngoai nuoc
                If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' ma lh de trong => mua trong nuoc
                    .Range("H" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia trong nuoc côt H
                Else
                    .Range("I" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia ngoai nuoc côt I
                End If
                
                
                ' dien các côt K,L,M,N,O ####################
          
                Dim item ' =  Dim item As Variant
                Dim cotK As String, cotL As String, cotM As String, cotN As String, cotO As String
                    keySave2 = CStr(.Range("Q" & j))
                    cotK = ""
                    cotL = ""
                    cotM = ""
                    cotN = ""
                    cotO = ""
                    If dictSave2.Exists(keySave2) Then
                        For Each item In dictSave2(keySave2) ' cho biên item lap trong collection = dictsave2
                            cotK = cotK & item(0) & ";" 'lay côt 1 là sô tkn
                            cotL = cotL & item(1) & ";" 'lay côt 1 là ngày tkn
                            cotO = cotO & item(2) & ";" 'lay côt 1 là sô ḍng hàng
                            cotM = cotM & item(3) & ";" 'lay côt 1 là sô form X,PL X, CO
                            cotN = cotN & item(4) & ";" 'lay côt 1 là ngày form X,PL X, CO
                            
                        Next ' xoá dâu ; o cuoi di
                            .Range("K" & j) = Left(cotK, Len(cotK) - 1)
                            .Range("L" & j) = Left(cotL, Len(cotL) - 1)
                            .Range("O" & j) = Left(cotO, Len(cotO) - 1)
                            If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' nêu xx là VN th́
                                .Range("M" & j) = Left(cotM, Len(cotM) - 1)
                                .Range("N" & j) = Left(cotN, Len(cotN) - 1)
                            End If
                    End If
            Next j
            
            'an hàng rong  khong chua du lieu
            Dim arrBangke As Variant
                arrBangke = .Range("A16:A1585").Value
                For k = 1 To UBound(arrBangke, 1)
                   If arrBangke(k, 1) = "" Then
                        .Rows((k + 15) & ":1585").Hidden = True
                        Exit For
                   End If
                Next k
            ' an cot du thua di
                   .Range("O1:Y1").EntireColumn.Hidden = True
                   

         Dim K10#, P10#, P1603#, P1604#
        Dim H1588#, I1588#
        Dim I1590#, I1591#, I1593#
        Dim I1595#, I1596#, I1597#, I1599#
        Dim I1600#, I1601#, I1602#, I1603#, I1604#
        Dim keyIncoterm As String
        Dim sumVNH As Double, sumVNI As Double, freight#

            ' Lay s?n các giá tri hay dùng
            K10 = .Range("K10").Value
            P10 = .Range("P10").Value
            P1603 = .Range("P1603").Value
            P1604 = .Range("P1604").Value
            keyIncoterm = .Range("O8").Value
        
            ' Tong có xx và ko có xx
            Dim arrBangKeH As Variant, arrBangKeI As Variant
            Dim sumH As Double, sumI As Double
            arrBangKeH = .Range("H16:H" & lastRowT).Value ' ḍng cuoi là dong dm
            arrBangKeI = .Range("I16:I" & lastRowT).Value ' ḍng cuoi là dong dm
            sumH = 0
            sumI = 0
                For k = 1 To UBound(arrBangKeH, 1)
                    If IsNumeric(arrBangKeH(k, 1)) Then
                        If IsNumeric(arrBangKeH(k, 1)) Then sumH = sumH + CDbl(arrBangKeH(k, 1)) ' tông côt H
                        If IsNumeric(arrBangKeI(k, 1)) Then sumI = sumI + CDbl(arrBangKeI(k, 1)) ' tông côt I
                    End If
                Next k
            .Range("H1588").Value = sumH
            .Range("C1586").Value = sumH
            .Range("I1588").Value = sumI
            .Range("C1587").Value = sumI
            .Range("K1606").Value = sumI
            
        
            ' Chi phí nhân công tr?c ti?p
            I1590 = .Range("P1590").Value * K10
            I1591 = .Range("P1591").Value * K10
            I1593 = I1590 + I1591
            .Range("I1590").Value = I1590
            .Range("I1591").Value = I1591
            .Range("I1593").Value = I1593
        
            ' Chi phí phân b?
            I1595 = .Range("P1595").Value * K10
            I1596 = .Range("P1596").Value * K10
            I1597 = .Range("P1597").Value * K10
            I1599 = I1595 + I1596 + I1597
            .Range("I1595").Value = I1595
            .Range("I1596").Value = I1596
            .Range("I1597").Value = I1597
            .Range("I1599").Value = I1599
        
            ' Chi phí xu?t xu?ng (IV)
            I1600 = sumH + sumI + I1593 + I1599
            .Range("I1600").Value = I1600
        
            ' X? lư theo di?u ki?n Incoterm
            Select Case UCase(keyIncoterm)
                Case "EXW", "FCR"
                    I1602 = K10
                    I1603 = (K10 / P10) * P1603
                    I1604 = K10 + I1603
                    I1601 = I1602 - I1600
        
                Case "FOB"
                    I1604 = K10
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
        
                Case Else ' CFR, CIF, DDU, DDP, ...
                    freight = (K10 / P10) * P1604
                    I1604 = K10 - freight
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    K10 = I1604 ' c?p nh?t l?i giá FOB
            End Select
        
            ' Ghi kêt qua
            .Range("I1601").Value = I1601
            .Range("I1602").Value = I1602
            .Range("I1603").Value = I1603
            .Range("I1604").Value = I1604
            .Range("K11").Value = I1604
        
            ' Ghi thông tin RVC
            .Range("J1606").Value = Round(I1604, 2) & "   - "
            .Range("J1609").Value = Round(I1604, 2)
            
    
    ' RVC %
    .Range("M1607").Value = Round((I1604 - .Range("K1606").Value) / I1604 * 100, 2) & " %"
    Dim percentText As String
    .Range("M1607").NumberFormat = "0.00%"
    percentText = .Range("M1607").Text  ' L?y n?i dung hi?n th? nhu "15.00%"
    .Range("B1611").Value = "K" & ChrW(7871) & "t lu" & ChrW(7853) & "n: H" & ChrW(224) & "ng h" & ChrW(243) & "a " & _
                            "d" & ChrW(225) & "p " & ChrW(7911) & "ng ti" & ChrW(234) & "u ch" & ChrW(237) & " " & ChrW(8220) & "RVC " & _
                             percentText & " + CTSH" & ChrW(8221)
          
        'copy LVC tu wb goc sang wb moi khoi tao
        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            Range("A1:AA1626").Copy
            Range("A1:AA1626").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = so & .Range("P7") ' dat ten sheet vua moi past
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh
         so = so + 1
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
    Next i ' kêt thúc vong lap i ////////////////////
    
    newWb.Activate ' quay tro ve wb moi khoi tao
    Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
    'wb.Close ' tat file excel

 
End With
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub

Sub runUpgradeRVC()
Dim lastRowW As Integer, lastRowT As Integer, lastRowXK As Double, lastRowDM As Long, lastRowSave As Double
Dim wsXK As Worksheet, wsDM As Worksheet, wsSave As Worksheet
Dim dictXK As Object, dictXKcot17 As Object, dictDM As Object, dictDMcot2 As Object, dictSave As Object, dictSave2 As Object
Dim arrXK As Variant, arrDM As Variant, arrSave As Variant
Dim i As Double
Dim colCountXK As Integer, colCountDM As Integer, colCountSave As Integer

Call unProtected
With ThisWorkbook.Sheets("RVC")
lastRowW = .Cells(.Rows.Count, "W").End(xlUp).row

    ' dat ten sheet
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsSave = ThisWorkbook.Sheets("Save")
    
    ' khoi tao dict
    Set dictXK = CreateObject("Scripting.Dictionary")
    Set dictXKcot17 = CreateObject("Scripting.Dictionary")
    Set dictDM = CreateObject("Scripting.Dictionary")
    Set dictDMcot2 = CreateObject("Scripting.Dictionary")
    Set dictSave = CreateObject("Scripting.Dictionary")
    Set dictSave2 = CreateObject("Scripting.Dictionary")
    
    
    
    'ḍng cuôi
    lastRowXK = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "B").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row
    
    ' khoi tao mang
    arrXK = wsXK.Range("A11:BB" & lastRowXK)
    arrDM = wsDM.Range("A7:Y" & lastRowDM)
    arrSave = wsSave.Range("A2:W" & lastRowSave)
    
    ' sô côt trong mang
    colCountXK = UBound(arrXK, 2)
    colCountDM = UBound(arrDM, 2)
    colCountSave = UBound(arrSave, 2)
    
'cài dat thoi han su dung
    Dim hanchot As Date
        hanchot = DateSerial(2026, 12, 31)
            If Now() > hanchot Then
                MsgBox "Qua han su dung " & CStr(hanchot)
                ThisWorkbook.Close SaveChanges:=False
            End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path
    sFileName = "RVC" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        
'I. dien du lieu header
    ' 1.1 gán data vào dictXK
    Dim arrRow As Variant ' tao mang tam dê chua ḍng
    Dim j As Double
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRow(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRow(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXK(arrXK(i, 2)) = arrRow ' ' Dùng côt 2 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
           
    '1.2 ghi data tu dictXK vào bang ke RVC
    Dim key As Variant
    key = Range("Q9").Value
    If dictXK.Exists(key) Then
        .Range("P6") = dictXK(key)(11) ' ty gia
        .Range("O8") = dictXK(key)(18) ' incoterm
    End If

    '1.3 t́m côt P10
    Dim total As Double
    total = 0
    For i = 1 To UBound(arrXK, 1)
        If arrXK(i, 2) = key Then
            If IsNumeric(arrXK(i, 31)) Then ' trap lôi
                total = total + arrXK(i, 31) ' tong tg nguyên tê
            End If
        End If
    Next i
    .Range("P10") = total
 
 ' II dien phân body bên trong bang kê
 ' khoi tao dict moi côt 17 là key xxxxxxxxxxxxxxxxx
 Dim arrRowcot17 As Variant ' tao mang tam dê chua ḍng
 Dim key2 As Variant
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRowcot17(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRowcot17(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXKcot17(CStr(arrXK(i, 17))) = arrRowcot17 ' ' Dùng côt 16 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
    
' tim so luong dong ma dinh muc sp
  ' khoi tao dictDM yyyyyyyyyyyyyyyyy
        Dim counifDM As Integer
        Dim keyDM As Variant
        For i = 1 To UBound(arrDM, 1)
            dictDM(CStr(arrDM(i, 1))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
    
  ' khoi tao dictDMcot2 moi de vlookup zzzzzzzzzzzzzzzzzzzzzzzzz
      Dim keyDM2 As Variant
      Dim stt As Integer
        For i = 1 To UBound(arrDM, 1)
            dictDMcot2(CStr(arrDM(i, 2))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
        
   ' khoi tao dictSave moi de vlookup wwwwwwwwwwwwwwwwwwwwww
        Dim keySave As Variant
        Dim arrsaveW As Variant
            For i = 1 To UBound(arrSave, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
              ReDim arrsaveW(1 To colCountSave) ' câp lai mang 1 chieu kích thuoc là sô côt w= 23
                For j = 1 To colCountSave
                  arrsaveW(j) = arrSave(i, j) 'Lây giá tri  ḍng i, côt j cua arrSave, gán vào vi trí j trong mang arrRow."
                Next j
                dictSave(CStr(arrSave(i, 23))) = arrsaveW ' Dùng côt 23 làm Key, và gán toàn bô ḍng & côt vào Value
            Next i
            
     'khoi tao dict de tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@
        Dim dictTong As Object, dictDem As Object
        Dim k As Long
        Dim keyTBC As String
        Dim donGia As Double
        Dim donGiaTBC As Double
        Set dictTong = CreateObject("Scripting.Dictionary")
        Set dictDem = CreateObject("Scripting.Dictionary")
        
            For k = 1 To UBound(arrSave, 1) ' duyet mang
                keyTBC = arrSave(k, 23) ' lây giá tri ḍng i côt 23 gán vào keyTBC
                If IsNumeric(arrSave(k, 9)) Then
                    donGia = arrSave(k, 9) 'lây don giá ḍng i côt 9 gán vào don giá
                    If dictTong.Exists(keyTBC) Then ' néu key tôn tai trong dict
                        dictTong(keyTBC) = dictTong(keyTBC) + donGia
                        dictDem(keyTBC) = dictDem(keyTBC) + 1
                    Else ' nguoc lai, nêu key ko tôn tai
                        dictTong.Add keyTBC, donGia ' lay don giá
                        dictDem.Add keyTBC, 1 ' sô lân xuât hien don giá = 1
                    End If
                 End If
            Next k
       
       ' khoi tao dictSave2 moi de vlookup #########################
       Dim arrSave2 As Variant
       Dim keySave2 As String
       Dim boxkeyValue As Collection 'trong Dictionary chi chua 1 giá tri duy nhât (không duoc trùng key), nên muôn luu nhiêu ḍng cho cùng 1 key, phai gom nhiêu ḍng vào 1 Collection
       For i = 1 To UBound(arrSave, 1) ' duyêt mang tu save de luu giá tri vào dictsave2
       keySave2 = CStr(arrSave(i, 23))
            arrSave2 = Array(arrSave(i, 1), arrSave(i, 2), arrSave(i, 4), arrSave(i, 14), arrSave(i, 15)) 'ghi côt 1,2,4,14,15
            If Not dictSave2.Exists(keySave2) Then ' nêu key ko tôn tai trong dict
                Set boxkeyValue = New Collection ' tao bo suu tâp chua data cua các key trùng nhau
                boxkeyValue.Add arrSave2 ' boxkey giông nhu là 1 mang trung gian
                dictSave2.Add keySave2, boxkeyValue ' ghi data t? boxkeyvalue vào dictsave2
            Else
                dictSave2(keySave2).Add arrSave2 ' nêu ko trung th́ ko cân boxkey, ghi truc tiep mang arrsave2 và dictsave2
            End If
       Next i
       

' bat dau vong lap chinh dien phan body/////////////////
        Dim so As Integer
        so = 1
    For i = 16 To lastRowW ' ****** cot moc vong lap de xuat file excel
        ThisWorkbook.Sheets("RVC").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & i) ' mă SP vao ô P7 xxxxxxxxxxxxxxxxxxxxxxxxxx
        '.Range("Q10") = .Range("W" & i) ' mă SP vao ô P7
        key2 = CStr(.Range("V" & i))
        If dictXKcot17.Exists(key2) Then
            .Range("K7") = dictXKcot17(key2)(23) 'tên sp
            .Range("K8") = Left(dictXKcot17(key2)(22), 6) 'HS code
            .Range("P8") = dictXKcot17(key2)(25) 'don giá
            .Range("L9") = dictXKcot17(key2)(28) 'dvt
            .Range("K9") = dictXKcot17(key2)(27) 'sl
            .Range("P9") = dictXKcot17(key2)(27) 'sl
            .Range("L10") = "USD"
            .Range("L11") = "USD"
            .Range("K10") = .Range("P8") * .Range("P9") ' tri gia tkx
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
        End If
        
  'tính countif  t́m sl ḍng dm yyyyyyyyyyyyyyyyyy
        keyDM = CStr(.Range("P7"))
        counifDM = 0
        For j = 1 To UBound(arrDM, 1)
            If arrDM(j, 1) = keyDM Then
                counifDM = counifDM + 1
            End If
        Next j
        .Range("P5") = counifDM ' gán sl vào dong cuoi o cot T
        .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
    
 'chay vong lap dien gia tri trong table zzzzzzzzzzzzzzzzzzz
        stt = 0
        lastRowT = .Cells(.Rows.Count, "T").End(xlUp).row
            For j = 16 To lastRowT
                 stt = stt + 1
                .Range("A" & j) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
                ' dien cot E(dm) và cot P mă NVL
                keyDM2 = CStr(stt & .Range("P7"))
                If dictDMcot2.Exists(keyDM2) Then
                    .Range("E" & j) = dictDMcot2(keyDM2)(3) ' dm
                    .Range("P" & j) = "'" & dictDMcot2(keyDM2)(2) 'mă nvl
                    .Range("F" & j) = .Range("E" & j) * .Range("P9") ' tinh sl
                    .Range("Q" & j) = "'" & .Range("Q9") & .Range("P" & j) ' tao cot phu
                End If
                
                ' dien các côt B,C,D,J,R,S wwwwwwwwwwwwwwwwwwwwwwww
                keySave = .Range("Q" & j)
                If dictSave.Exists(keySave) Then
                    .Range("B" & j) = dictSave(keySave)(7) ' tên nvl
                    .Range("C" & j) = Left(dictSave(keySave)(6), 6) ' HS code
                    .Range("D" & j) = dictSave(keySave)(12) ' dvt
                    .Range("J" & j) = dictSave(keySave)(8) ' xuât xu
                    .Range("R" & j) = dictSave(keySave)(16) ' ty giá
                    .Range("S" & j) = dictSave(keySave)(3) ' loai h́nh
                End If
                
                
                'tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
                If dictTong.Exists(keySave) Then
                    donGiaTBC = dictTong(keySave) / dictDem(keySave)
                    .Range("G" & j) = donGiaTBC ' tính trung b́nh công côt G
                End If
                
                '  tinh tri giá có XX & ko có XX
                If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' ma lh de trong => mua trong nuoc
                    .Range("H" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia trong nuoc côt H
                Else
                    .Range("I" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia ngoai nuoc côt I
                End If
                
                
                ' dien các côt K,L,M,N,O ####################
          
                Dim item ' =  Dim item As Variant
                Dim cotK As String, cotL As String, cotM As String, cotN As String, cotO As String
                    keySave2 = CStr(.Range("Q" & j))
                    cotK = ""
                    cotL = ""
                    cotM = ""
                    cotN = ""
                    cotO = ""
                    If dictSave2.Exists(keySave2) Then
                        For Each item In dictSave2(keySave2) ' cho biên item lap trong collection = dictsave2
                            cotK = cotK & item(0) & ";" 'lay côt 1 là sô tkn
                            cotL = cotL & item(1) & ";" 'lay côt 1 là ngày tkn
                            cotO = cotO & item(2) & ";" 'lay côt 1 là sô ḍng hàng
                            cotM = cotM & item(3) & ";" 'lay côt 1 là sô form X,PL X, CO
                            cotN = cotN & item(4) & ";" 'lay côt 1 là ngày form X,PL X, CO
                            
                        Next ' xoá dâu ; o cuoi di
                            .Range("K" & j) = Left(cotK, Len(cotK) - 1)
                            .Range("L" & j) = Left(cotL, Len(cotL) - 1)
                            .Range("O" & j) = Left(cotO, Len(cotO) - 1)
                            If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' nêu xx là VN th́
                                .Range("M" & j) = Left(cotM, Len(cotM) - 1)
                                .Range("N" & j) = Left(cotN, Len(cotN) - 1)
                            End If
                    End If
            Next j
            
            'an hàng rong  khong chua du lieu
            Dim arrBangke As Variant
                arrBangke = .Range("A16:A1585").Value
                For k = 1 To UBound(arrBangke, 1)
                   If arrBangke(k, 1) = "" Then
                        .Rows((k + 15) & ":1585").Hidden = True
                        Exit For
                   End If
                Next k
            ' an cot du thua di
                   .Range("O1:Y1").EntireColumn.Hidden = True
                   

        Dim K10#, P10#, P1603#, P1604#
        Dim H1588#, I1588#
        Dim I1590#, I1591#, I1593#
        Dim I1595#, I1596#, I1597#, I1599#
        Dim I1600#, I1601#, I1602#, I1603#, I1604#
        Dim keyIncoterm As String
        Dim sumVNH As Double, sumVNI As Double, freight#

            ' Lay s?n các giá tri hay dùng
            K10 = .Range("K10").Value
            P10 = .Range("P10").Value
            P1603 = .Range("P1603").Value
            P1604 = .Range("P1604").Value
            keyIncoterm = .Range("O8").Value
        
            ' Tong có xx và ko có xx
            Dim arrBangKeH As Variant, arrBangKeI As Variant
            Dim sumH As Double, sumI As Double
            arrBangKeH = .Range("H16:H" & lastRowT).Value ' ḍng cuoi là dong dm
            arrBangKeI = .Range("I16:I" & lastRowT).Value ' ḍng cuoi là dong dm
            sumH = 0
            sumI = 0
                For k = 1 To UBound(arrBangKeH, 1)
                    If IsNumeric(arrBangKeH(k, 1)) Then
                        If IsNumeric(arrBangKeH(k, 1)) Then sumH = sumH + CDbl(arrBangKeH(k, 1)) ' tông côt H
                        If IsNumeric(arrBangKeI(k, 1)) Then sumI = sumI + CDbl(arrBangKeI(k, 1)) ' tông côt I
                    End If
                Next k
            .Range("H1588").Value = sumH
            .Range("C1586").Value = sumH
            .Range("I1588").Value = sumI
            .Range("C1587").Value = sumI
            .Range("K1606").Value = sumI
            
        
            ' Chi phí nhân công tr?c ti?p
            I1590 = .Range("P1590").Value * K10
            I1591 = .Range("P1591").Value * K10
            I1593 = I1590 + I1591
            .Range("I1590").Value = I1590
            .Range("I1591").Value = I1591
            .Range("I1593").Value = I1593
        
            ' Chi phí phân b?
            I1595 = .Range("P1595").Value * K10
            I1596 = .Range("P1596").Value * K10
            I1597 = .Range("P1597").Value * K10
            I1599 = I1595 + I1596 + I1597
            .Range("I1595").Value = I1595
            .Range("I1596").Value = I1596
            .Range("I1597").Value = I1597
            .Range("I1599").Value = I1599
        
            ' Chi phí xu?t xu?ng (IV)
            I1600 = sumH + sumI + I1593 + I1599
            .Range("I1600").Value = I1600
        
            ' X? lư theo di?u ki?n Incoterm
            Select Case UCase(keyIncoterm)
                Case "EXW", "FCR"
                    I1602 = K10
                    I1603 = (K10 / P10) * P1603
                    I1604 = K10 + I1603
                    I1601 = I1602 - I1600
        
                Case "FOB"
                    I1604 = K10
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
        
                Case Else ' CFR, CIF, DDU, DDP, ...
                    freight = (K10 / P10) * P1604
                    I1604 = K10 - freight
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    K10 = I1604 ' c?p nh?t l?i giá FOB
            End Select
        
            ' Ghi kêt qua
            .Range("I1601").Value = I1601
            .Range("I1602").Value = I1602
            .Range("I1603").Value = I1603
            .Range("I1604").Value = I1604
            .Range("K11").Value = I1604
        
            ' Ghi thông tin RVC
            .Range("J1606").Value = Round(I1604, 2) & "   - "
            .Range("J1609").Value = Round(I1604, 2)
            
    
    ' RVC %
    .Range("M1607").Value = Round((I1604 - .Range("K1606").Value) / I1604 * 100, 2) & " %"
    Dim percentText As String
    .Range("M1607").NumberFormat = "0.00%"
    percentText = .Range("M1607").Text  ' L?y n?i dung hi?n th? nhu "15.00%"
    .Range("B1611").Value = "K" & ChrW(7871) & "t lu" & ChrW(7853) & "n: H" & ChrW(224) & "ng h" & ChrW(243) & "a " & _
                            "d" & ChrW(225) & "p " & ChrW(7911) & "ng ti" & ChrW(234) & "u ch" & ChrW(237) & " " & ChrW(8220) & "RVC " & _
                             percentText & " + CTSH" & ChrW(8221)
          
        'copy RVC tu wb goc sang wb moi khoi tao
        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            Range("A1:AA1626").Copy
            Range("A1:AA1626").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = so & .Range("P7") ' dat ten sheet vua moi past
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh
         so = so + 1
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
    Next i ' kêt thúc vong lap i ////////////////////
    
    newWb.Activate ' quay tro ve wb moi khoi tao
    Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
    'wb.Close ' tat file excel

 
End With
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub



Sub runUpgradeCTH()
Dim lastRowW As Integer, lastRowT As Integer, lastRowXK As Double, lastRowDM As Long, lastRowSave As Double
Dim wsXK As Worksheet, wsDM As Worksheet, wsSave As Worksheet
Dim dictXK As Object, dictXKcot17 As Object, dictDM As Object, dictDMcot2 As Object, dictSave As Object, dictSave2 As Object
Dim arrXK As Variant, arrDM As Variant, arrSave As Variant
Dim i As Double
Dim colCountXK As Integer, colCountDM As Integer, colCountSave As Integer
Call unProtected

With ThisWorkbook.Sheets("CTH")
lastRowW = .Cells(.Rows.Count, "W").End(xlUp).row

    ' dat ten sheet
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsSave = ThisWorkbook.Sheets("Save")
    
    ' khoi tao dict
    Set dictXK = CreateObject("Scripting.Dictionary")
    Set dictXKcot17 = CreateObject("Scripting.Dictionary")
    Set dictDM = CreateObject("Scripting.Dictionary")
    Set dictDMcot2 = CreateObject("Scripting.Dictionary")
    Set dictSave = CreateObject("Scripting.Dictionary")
    Set dictSave2 = CreateObject("Scripting.Dictionary")
    
    
    
    'ḍng cuôi
    lastRowXK = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "B").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row
    
    ' khoi tao mang
    arrXK = wsXK.Range("A11:BB" & lastRowXK)
    arrDM = wsDM.Range("A7:Y" & lastRowDM)
    arrSave = wsSave.Range("A2:W" & lastRowSave)
    
    ' sô côt trong mang
    colCountXK = UBound(arrXK, 2)
    colCountDM = UBound(arrDM, 2)
    colCountSave = UBound(arrSave, 2)
    
'cài dat thoi han su dung
    Dim hanchot As Date
        hanchot = DateSerial(2026, 12, 31)
            If Now() > hanchot Then
                MsgBox "Qua han su dung " & CStr(hanchot)
                ThisWorkbook.Close SaveChanges:=False
            End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path
    sFileName = "CTH" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        
'I. dien du lieu header
    ' 1.1 gán data vào dictXK
    Dim arrRow As Variant ' tao mang tam dê chua ḍng
    Dim j As Double
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRow(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRow(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXK(arrXK(i, 2)) = arrRow ' ' Dùng côt 2 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
           
    '1.2 ghi data tu dictXK vào bang ke CTH
    Dim key As Variant
    key = Range("Q9").Value
    If dictXK.Exists(key) Then
        .Range("P6") = dictXK(key)(11) ' ty gia
        .Range("O8") = dictXK(key)(18) ' incoterm
    End If

    '1.3 t́m côt P10
    Dim total As Double
    total = 0
    For i = 1 To UBound(arrXK, 1)
        If arrXK(i, 2) = key Then
            If IsNumeric(arrXK(i, 31)) Then ' trap lôi
                total = total + arrXK(i, 31) ' tong tg nguyên tê
            End If
        End If
    Next i
    .Range("P10") = total
 
 ' II dien phân body bên trong bang kê
 ' khoi tao dict moi côt 17 là key xxxxxxxxxxxxxxxxx
 Dim arrRowcot17 As Variant ' tao mang tam dê chua ḍng
 Dim key2 As Variant
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRowcot17(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRowcot17(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXKcot17(CStr(arrXK(i, 17))) = arrRowcot17 ' ' Dùng côt 16 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
    
' tim so luong dong ma dinh muc sp
  ' khoi tao dictDM yyyyyyyyyyyyyyyyy
        Dim counifDM As Integer
        Dim keyDM As Variant
        For i = 1 To UBound(arrDM, 1)
            dictDM(CStr(arrDM(i, 1))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
    
  ' khoi tao dictDMcot2 moi de vlookup zzzzzzzzzzzzzzzzzzzzzzzzz
      Dim keyDM2 As Variant
      Dim stt As Integer
        For i = 1 To UBound(arrDM, 1)
            dictDMcot2(CStr(arrDM(i, 2))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
        
   ' khoi tao dictSave moi de vlookup wwwwwwwwwwwwwwwwwwwwww
        Dim keySave As Variant
        Dim arrsaveW As Variant
            For i = 1 To UBound(arrSave, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
              ReDim arrsaveW(1 To colCountSave) ' câp lai mang 1 chieu kích thuoc là sô côt w= 23
                For j = 1 To colCountSave
                  arrsaveW(j) = arrSave(i, j) 'Lây giá tri  ḍng i, côt j cua arrSave, gán vào vi trí j trong mang arrRow."
                Next j
                dictSave(CStr(arrSave(i, 23))) = arrsaveW ' Dùng côt 23 làm Key, và gán toàn bô ḍng & côt vào Value
            Next i
            
     'khoi tao dict de tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@
        Dim dictTong As Object, dictDem As Object
        Dim k As Long
        Dim keyTBC As String
        Dim donGia As Double
        Dim donGiaTBC As Double
        Set dictTong = CreateObject("Scripting.Dictionary")
        Set dictDem = CreateObject("Scripting.Dictionary")
        
            For k = 1 To UBound(arrSave, 1) ' duyet mang
                keyTBC = arrSave(k, 23) ' lây giá tri ḍng i côt 23 gán vào keyTBC
                If IsNumeric(arrSave(k, 9)) Then
                    donGia = arrSave(k, 9) 'lây don giá ḍng i côt 9 gán vào don giá
                    If dictTong.Exists(keyTBC) Then ' néu key tôn tai trong dict
                        dictTong(keyTBC) = dictTong(keyTBC) + donGia
                        dictDem(keyTBC) = dictDem(keyTBC) + 1
                    Else ' nguoc lai, nêu key ko tôn tai
                        dictTong.Add keyTBC, donGia ' lay don giá
                        dictDem.Add keyTBC, 1 ' sô lân xuât hien don giá = 1
                    End If
                 End If
            Next k
       
       ' khoi tao dictSave2 moi de vlookup #########################
       Dim arrSave2 As Variant
       Dim keySave2 As String
       Dim boxkeyValue As Collection 'trong Dictionary chi chua 1 giá tri duy nhât (không duoc trùng key), nên muôn luu nhiêu ḍng cho cùng 1 key, phai gom nhiêu ḍng vào 1 Collection
       For i = 1 To UBound(arrSave, 1) ' duyêt mang tu save de luu giá tri vào dictsave2
       keySave2 = CStr(arrSave(i, 23))
            arrSave2 = Array(arrSave(i, 1), arrSave(i, 2), arrSave(i, 4), arrSave(i, 14), arrSave(i, 15)) 'ghi côt 1,2,4,14,15
            If Not dictSave2.Exists(keySave2) Then ' nêu key ko tôn tai trong dict
                Set boxkeyValue = New Collection ' tao bo suu tâp chua data cua các key trùng nhau
                boxkeyValue.Add arrSave2 ' boxkey giông nhu là 1 mang trung gian
                dictSave2.Add keySave2, boxkeyValue ' ghi data t? boxkeyvalue vào dictsave2
            Else
                dictSave2(keySave2).Add arrSave2 ' nêu ko trung th́ ko cân boxkey, ghi truc tiep mang arrsave2 và dictsave2
            End If
       Next i
       

' bat dau vong lap chinh dien phan body/////////////////
        Dim so As Integer
        so = 1
    For i = 16 To lastRowW ' ****** cot moc vong lap de xuat file excel
        ThisWorkbook.Sheets("CTH").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & i) ' mă SP vao ô P7 xxxxxxxxxxxxxxxxxxxxxxxxxx
        '.Range("Q10") = .Range("W" & i) ' mă SP vao ô P7
        key2 = CStr(.Range("V" & i))
        If dictXKcot17.Exists(key2) Then
            .Range("K7") = dictXKcot17(key2)(23) 'tên sp
            .Range("K8") = Left(dictXKcot17(key2)(22), 6) 'HS code
            .Range("P8") = dictXKcot17(key2)(25) 'don giá
            .Range("L9") = dictXKcot17(key2)(28) 'dvt
            .Range("K9") = dictXKcot17(key2)(27) 'sl
            .Range("P9") = dictXKcot17(key2)(27) 'sl
            .Range("L10") = "USD"
            .Range("L11") = "USD"
            .Range("K10") = .Range("P8") * .Range("P9") ' tri gia tkx
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
        End If
        
  'tính countif  t́m sl ḍng dm yyyyyyyyyyyyyyyyyy
        keyDM = CStr(.Range("P7"))
        counifDM = 0
        For j = 1 To UBound(arrDM, 1)
            If arrDM(j, 1) = keyDM Then
                counifDM = counifDM + 1
            End If
        Next j
        .Range("P5") = counifDM ' gán sl vào dong cuoi o cot T
        .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
    
 'chay vong lap dien gia tri trong table zzzzzzzzzzzzzzzzzzz
        stt = 0
        lastRowT = .Cells(.Rows.Count, "T").End(xlUp).row
            For j = 16 To lastRowT
                 stt = stt + 1
                .Range("A" & j) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
                ' dien cot E(dm) và cot P mă NVL
                keyDM2 = CStr(stt & .Range("P7"))
                If dictDMcot2.Exists(keyDM2) Then
                    .Range("E" & j) = dictDMcot2(keyDM2)(3) ' dm
                    .Range("P" & j) = dictDMcot2(keyDM2)(2) 'mă nvl
                    .Range("F" & j) = .Range("E" & j) * .Range("P9") ' tinh sl
                    .Range("Q" & j) = "'" & .Range("Q9") & .Range("P" & j) ' tao cot phu
                End If
                
                ' dien các côt B,C,D,J,R,S wwwwwwwwwwwwwwwwwwwwwwww
                keySave = .Range("Q" & j)
                If dictSave.Exists(keySave) Then
                    .Range("B" & j) = dictSave(keySave)(7) ' tên nvl
                    .Range("C" & j) = Left(dictSave(keySave)(6), 6) ' HS code
                    .Range("D" & j) = dictSave(keySave)(12) ' dvt
                    .Range("J" & j) = dictSave(keySave)(8) ' xuât xu
                    .Range("R" & j) = dictSave(keySave)(16) ' ty giá
                    .Range("S" & j) = dictSave(keySave)(3) ' loai h́nh
                End If
                
                
                'tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
                If dictTong.Exists(keySave) Then
                    donGiaTBC = dictTong(keySave) / dictDem(keySave)
                    .Range("G" & j) = donGiaTBC ' tính trung b́nh công côt G
                End If
                
                '  tinh tri giá có XX & ko có XX
                If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' ma lh de trong => mua trong nuoc
                    .Range("H" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia trong nuoc côt H
                Else
                    .Range("I" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia ngoai nuoc côt I
                End If
                
                
                ' dien các côt K,L,M,N,O ####################
          
                Dim item ' =  Dim item As Variant
                Dim cotK As String, cotL As String, cotM As String, cotN As String, cotO As String
                    keySave2 = CStr(.Range("Q" & j))
                    cotK = ""
                    cotL = ""
                    cotM = ""
                    cotN = ""
                    cotO = ""
                    If dictSave2.Exists(keySave2) Then
                        For Each item In dictSave2(keySave2) ' cho biên item lap trong collection = dictsave2
                            cotK = cotK & item(0) & ";" 'lay côt 1 là sô tkn
                            cotL = cotL & item(1) & ";" 'lay côt 1 là ngày tkn
                            cotO = cotO & item(2) & ";" 'lay côt 1 là sô ḍng hàng
                            cotM = cotM & item(3) & ";" 'lay côt 1 là sô form X,PL X, CO
                            cotN = cotN & item(4) & ";" 'lay côt 1 là ngày form X,PL X, CO
                            
                        Next ' xoá dâu ; o cuoi di
                            .Range("K" & j) = Left(cotK, Len(cotK) - 1)
                            .Range("L" & j) = Left(cotL, Len(cotL) - 1)
                            .Range("O" & j) = Left(cotO, Len(cotO) - 1)
                            If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' nêu xx là VN th́
                                .Range("M" & j) = Left(cotM, Len(cotM) - 1)
                                .Range("N" & j) = Left(cotN, Len(cotN) - 1)
                            End If
                    End If
            Next j
            
            'an hàng rong  khong chua du lieu
            Dim arrBangke As Variant
                arrBangke = .Range("A16:A1585").Value
                For k = 1 To UBound(arrBangke, 1)
                   If arrBangke(k, 1) = "" Then
                        .Rows((k + 15) & ":1585").Hidden = True
                        Exit For
                   End If
                Next k
            ' an cot du thua di
                   .Range("O1:Y1").EntireColumn.Hidden = True
                   

        Dim K10#, P10#, P1603#, P1604#
        Dim H1588#, I1588#
        Dim I1590#, I1591#, I1593#
        Dim I1595#, I1596#, I1597#, I1599#
        Dim I1600#, I1601#, I1602#, I1603#, I1604#
        Dim keyIncoterm As String
        Dim sumVNH As Double, sumVNI As Double, freight#

            ' Lay s?n các giá tri hay dùng
            K10 = .Range("K10").Value
            P10 = .Range("P10").Value
            P1603 = .Range("P1603").Value
            P1604 = .Range("P1604").Value
            keyIncoterm = .Range("O8").Value
        
            ' Tong có xx và ko có xx
            Dim arrBangKeH As Variant, arrBangKeI As Variant
            Dim sumH As Double, sumI As Double
            arrBangKeH = .Range("H16:H" & lastRowT).Value ' ḍng cuoi là dong dm
            arrBangKeI = .Range("I16:I" & lastRowT).Value ' ḍng cuoi là dong dm
            sumH = 0
            sumI = 0
                For k = 1 To UBound(arrBangKeH, 1)
                    If IsNumeric(arrBangKeH(k, 1)) Then
                        If IsNumeric(arrBangKeH(k, 1)) Then sumH = sumH + CDbl(arrBangKeH(k, 1)) ' tông côt H
                        If IsNumeric(arrBangKeI(k, 1)) Then sumI = sumI + CDbl(arrBangKeI(k, 1)) ' tông côt I
                    End If
                Next k
            .Range("H1588").Value = sumH
            .Range("C1586").Value = sumH
            .Range("I1588").Value = sumI
            .Range("C1587").Value = sumI
            .Range("K1606").Value = sumI
            
        
            ' Chi phí nhân công tr?c ti?p
            I1590 = .Range("P1590").Value * K10
            I1591 = .Range("P1591").Value * K10
            I1593 = I1590 + I1591
            .Range("I1590").Value = I1590
            .Range("I1591").Value = I1591
            .Range("I1593").Value = I1593
        
            ' Chi phí phân b?
            I1595 = .Range("P1595").Value * K10
            I1596 = .Range("P1596").Value * K10
            I1597 = .Range("P1597").Value * K10
            I1599 = I1595 + I1596 + I1597
            .Range("I1595").Value = I1595
            .Range("I1596").Value = I1596
            .Range("I1597").Value = I1597
            .Range("I1599").Value = I1599
        
            ' Chi phí xu?t xu?ng (IV)
            I1600 = sumH + sumI + I1593 + I1599
            .Range("I1600").Value = I1600
        
            ' X? lư theo di?u ki?n Incoterm
            Select Case UCase(keyIncoterm)
                Case "EXW", "FCR"
                    I1602 = K10
                    I1603 = (K10 / P10) * P1603
                    I1604 = K10 + I1603
                    I1601 = I1602 - I1600
        
                Case "FOB"
                    I1604 = K10
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
        
                Case Else ' CFR, CIF, DDU, DDP, ...
                    freight = (K10 / P10) * P1604
                    I1604 = K10 - freight
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    K10 = I1604 ' c?p nh?t l?i giá FOB
            End Select
        
            ' Ghi kêt qua
            .Range("I1601").Value = I1601
            .Range("I1602").Value = I1602
            .Range("I1603").Value = I1603
            .Range("I1604").Value = I1604
            .Range("K11").Value = I1604
        
            ' Ghi thông tin CTH
            .Range("J1606").Value = Round(I1604, 2) & "   - "
            .Range("J1609").Value = Round(I1604, 2)
            
    
    ' CTH %
    .Range("M1607").Value = Round((I1604 - .Range("K1606").Value) / I1604 * 100, 2) & " %"
          
        'copy CTH tu wb goc sang wb moi khoi tao
        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            Range("A1:AA1626").Copy
            Range("A1:AA1626").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = so & .Range("P7") ' dat ten sheet vua moi past
            
             ' tao file PDF ****
            
            
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh
         so = so + 1
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
    Next i ' kêt thúc vong lap i ////////////////////
    
    newWb.Activate ' quay tro ve wb moi khoi tao
    Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
    'wb.Close ' tat file excel

 
End With
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub


Sub runUpgradeCTSH()
Dim lastRowW As Integer, lastRowT As Integer, lastRowXK As Double, lastRowDM As Long, lastRowSave As Double
Dim wsXK As Worksheet, wsDM As Worksheet, wsSave As Worksheet
Dim dictXK As Object, dictXKcot17 As Object, dictDM As Object, dictDMcot2 As Object, dictSave As Object, dictSave2 As Object
Dim arrXK As Variant, arrDM As Variant, arrSave As Variant
Dim i As Double
Dim colCountXK As Integer, colCountDM As Integer, colCountSave As Integer

Call unProtected
With ThisWorkbook.Sheets("CTSH")
lastRowW = .Cells(.Rows.Count, "W").End(xlUp).row

    ' dat ten sheet
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsSave = ThisWorkbook.Sheets("Save")
    
    ' khoi tao dict
    Set dictXK = CreateObject("Scripting.Dictionary")
    Set dictXKcot17 = CreateObject("Scripting.Dictionary")
    Set dictDM = CreateObject("Scripting.Dictionary")
    Set dictDMcot2 = CreateObject("Scripting.Dictionary")
    Set dictSave = CreateObject("Scripting.Dictionary")
    Set dictSave2 = CreateObject("Scripting.Dictionary")
    
    
    
    'ḍng cuôi
    lastRowXK = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "B").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row
    
    ' khoi tao mang
    arrXK = wsXK.Range("A11:BB" & lastRowXK)
    arrDM = wsDM.Range("A7:Y" & lastRowDM)
    arrSave = wsSave.Range("A2:W" & lastRowSave)
    
    ' sô côt trong mang
    colCountXK = UBound(arrXK, 2)
    colCountDM = UBound(arrDM, 2)
    colCountSave = UBound(arrSave, 2)
    
'cài dat thoi han su dung
    Dim hanchot As Date
        hanchot = DateSerial(2026, 12, 31)
            If Now() > hanchot Then
                MsgBox "Qua han su dung " & CStr(hanchot)
                ThisWorkbook.Close SaveChanges:=False
            End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path
    sFileName = "CTSH" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        
'I. dien du lieu header
    ' 1.1 gán data vào dictXK
    Dim arrRow As Variant ' tao mang tam dê chua ḍng
    Dim j As Double
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRow(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRow(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXK(arrXK(i, 2)) = arrRow ' ' Dùng côt 2 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
           
    '1.2 ghi data tu dictXK vào bang ke CTSH
    Dim key As Variant
    key = Range("Q9").Value
    If dictXK.Exists(key) Then
        .Range("P6") = dictXK(key)(11) ' ty gia
        .Range("O8") = dictXK(key)(18) ' incoterm
    End If

    '1.3 t́m côt P10
    Dim total As Double
    total = 0
    For i = 1 To UBound(arrXK, 1)
        If arrXK(i, 2) = key Then
            If IsNumeric(arrXK(i, 31)) Then ' trap lôi
                total = total + arrXK(i, 31) ' tong tg nguyên tê
            End If
        End If
    Next i
    .Range("P10") = total
 
 ' II dien phân body bên trong bang kê
 ' khoi tao dict moi côt 17 là key xxxxxxxxxxxxxxxxx
 Dim arrRowcot17 As Variant ' tao mang tam dê chua ḍng
 Dim key2 As Variant
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRowcot17(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRowcot17(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXKcot17(CStr(arrXK(i, 17))) = arrRowcot17 ' ' Dùng côt 16 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
    
' tim so luong dong ma dinh muc sp
  ' khoi tao dictDM yyyyyyyyyyyyyyyyy
        Dim counifDM As Integer
        Dim keyDM As Variant
        For i = 1 To UBound(arrDM, 1)
            dictDM(CStr(arrDM(i, 1))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
    
  ' khoi tao dictDMcot2 moi de vlookup zzzzzzzzzzzzzzzzzzzzzzzzz
      Dim keyDM2 As Variant
      Dim stt As Integer
        For i = 1 To UBound(arrDM, 1)
            dictDMcot2(CStr(arrDM(i, 2))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
        
   ' khoi tao dictSave moi de vlookup wwwwwwwwwwwwwwwwwwwwww
        Dim keySave As Variant
        Dim arrsaveW As Variant
            For i = 1 To UBound(arrSave, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
              ReDim arrsaveW(1 To colCountSave) ' câp lai mang 1 chieu kích thuoc là sô côt w= 23
                For j = 1 To colCountSave
                  arrsaveW(j) = arrSave(i, j) 'Lây giá tri  ḍng i, côt j cua arrSave, gán vào vi trí j trong mang arrRow."
                Next j
                dictSave(CStr(arrSave(i, 23))) = arrsaveW ' Dùng côt 23 làm Key, và gán toàn bô ḍng & côt vào Value
            Next i
            
     'khoi tao dict de tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@
        Dim dictTong As Object, dictDem As Object
        Dim k As Long
        Dim keyTBC As String
        Dim donGia As Double
        Dim donGiaTBC As Double
        Set dictTong = CreateObject("Scripting.Dictionary")
        Set dictDem = CreateObject("Scripting.Dictionary")
        
            For k = 1 To UBound(arrSave, 1) ' duyet mang
                keyTBC = arrSave(k, 23) ' lây giá tri ḍng i côt 23 gán vào keyTBC
                If IsNumeric(arrSave(k, 9)) Then
                    donGia = arrSave(k, 9) 'lây don giá ḍng i côt 9 gán vào don giá
                    If dictTong.Exists(keyTBC) Then ' néu key tôn tai trong dict
                        dictTong(keyTBC) = dictTong(keyTBC) + donGia
                        dictDem(keyTBC) = dictDem(keyTBC) + 1
                    Else ' nguoc lai, nêu key ko tôn tai
                        dictTong.Add keyTBC, donGia ' lay don giá
                        dictDem.Add keyTBC, 1 ' sô lân xuât hien don giá = 1
                    End If
                 End If
            Next k
       
       ' khoi tao dictSave2 moi de vlookup #########################
       Dim arrSave2 As Variant
       Dim keySave2 As String
       Dim boxkeyValue As Collection 'trong Dictionary chi chua 1 giá tri duy nhât (không duoc trùng key), nên muôn luu nhiêu ḍng cho cùng 1 key, phai gom nhiêu ḍng vào 1 Collection
       For i = 1 To UBound(arrSave, 1) ' duyêt mang tu save de luu giá tri vào dictsave2
       keySave2 = CStr(arrSave(i, 23))
            arrSave2 = Array(arrSave(i, 1), arrSave(i, 2), arrSave(i, 4), arrSave(i, 14), arrSave(i, 15)) 'ghi côt 1,2,4,14,15
            If Not dictSave2.Exists(keySave2) Then ' nêu key ko tôn tai trong dict
                Set boxkeyValue = New Collection ' tao bo suu tâp chua data cua các key trùng nhau
                boxkeyValue.Add arrSave2 ' boxkey giông nhu là 1 mang trung gian
                dictSave2.Add keySave2, boxkeyValue ' ghi data t? boxkeyvalue vào dictsave2
            Else
                dictSave2(keySave2).Add arrSave2 ' nêu ko trung th́ ko cân boxkey, ghi truc tiep mang arrsave2 và dictsave2
            End If
       Next i
       

' bat dau vong lap chinh dien phan body/////////////////
        Dim so As Integer
        so = 1
    For i = 16 To lastRowW ' ****** cot moc vong lap de xuat file excel
        ThisWorkbook.Sheets("CTSH").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & i) ' mă SP vao ô P7 xxxxxxxxxxxxxxxxxxxxxxxxxx
        '.Range("Q10") = .Range("W" & i) ' mă SP vao ô P7
        key2 = CStr(.Range("V" & i))
        If dictXKcot17.Exists(key2) Then
            .Range("K7") = dictXKcot17(key2)(23) 'tên sp
            .Range("K8") = Left(dictXKcot17(key2)(22), 6) 'HS code
            .Range("P8") = dictXKcot17(key2)(25) 'don giá
            .Range("L9") = dictXKcot17(key2)(28) 'dvt
            .Range("K9") = dictXKcot17(key2)(27) 'sl
            .Range("P9") = dictXKcot17(key2)(27) 'sl
            .Range("L10") = "USD"
            .Range("L11") = "USD"
            .Range("K10") = .Range("P8") * .Range("P9") ' tri gia tkx
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
        End If
        
  'tính countif  t́m sl ḍng dm yyyyyyyyyyyyyyyyyy
        keyDM = CStr(.Range("P7"))
        counifDM = 0
        For j = 1 To UBound(arrDM, 1)
            If arrDM(j, 1) = keyDM Then
                counifDM = counifDM + 1
            End If
        Next j
        .Range("P5") = counifDM ' gán sl vào dong cuoi o cot T
        .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
    
 'chay vong lap dien gia tri trong table zzzzzzzzzzzzzzzzzzz
        stt = 0
        lastRowT = .Cells(.Rows.Count, "T").End(xlUp).row
            For j = 16 To lastRowT
                 stt = stt + 1
                .Range("A" & j) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
                ' dien cot E(dm) và cot P mă NVL
                keyDM2 = CStr(stt & .Range("P7"))
                If dictDMcot2.Exists(keyDM2) Then
                    .Range("E" & j) = dictDMcot2(keyDM2)(3) ' dm
                    .Range("P" & j) = dictDMcot2(keyDM2)(2) 'mă nvl
                    .Range("F" & j) = .Range("E" & j) * .Range("P9") ' tinh sl
                    .Range("Q" & j) = "'" & .Range("Q9") & .Range("P" & j) ' tao cot phu
                End If
                
                ' dien các côt B,C,D,J,R,S wwwwwwwwwwwwwwwwwwwwwwww
                keySave = .Range("Q" & j)
                If dictSave.Exists(keySave) Then
                    .Range("B" & j) = dictSave(keySave)(7) ' tên nvl
                    .Range("C" & j) = Left(dictSave(keySave)(6), 6) ' HS code
                    .Range("D" & j) = dictSave(keySave)(12) ' dvt
                    .Range("J" & j) = dictSave(keySave)(8) ' xuât xu
                    .Range("R" & j) = dictSave(keySave)(16) ' ty giá
                    .Range("S" & j) = dictSave(keySave)(3) ' loai h́nh
                End If
                
                
                'tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
                If dictTong.Exists(keySave) Then
                    donGiaTBC = dictTong(keySave) / dictDem(keySave)
                    .Range("G" & j) = donGiaTBC ' tính trung b́nh công côt G
                End If
                
                '  tinh tri giá có XX & ko có XX
                If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' ma lh de trong => mua trong nuoc
                    .Range("H" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia trong nuoc côt H
                Else
                    .Range("I" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia ngoai nuoc côt I
                End If
                
                
                ' dien các côt K,L,M,N,O ####################
          
                Dim item ' =  Dim item As Variant
                Dim cotK As String, cotL As String, cotM As String, cotN As String, cotO As String
                    keySave2 = CStr(.Range("Q" & j))
                    cotK = ""
                    cotL = ""
                    cotM = ""
                    cotN = ""
                    cotO = ""
                    If dictSave2.Exists(keySave2) Then
                        For Each item In dictSave2(keySave2) ' cho biên item lap trong collection = dictsave2
                            cotK = cotK & item(0) & ";" 'lay côt 1 là sô tkn
                            cotL = cotL & item(1) & ";" 'lay côt 1 là ngày tkn
                            cotO = cotO & item(2) & ";" 'lay côt 1 là sô ḍng hàng
                            cotM = cotM & item(3) & ";" 'lay côt 1 là sô form X,PL X, CO
                            cotN = cotN & item(4) & ";" 'lay côt 1 là ngày form X,PL X, CO
                            
                        Next ' xoá dâu ; o cuoi di
                            .Range("K" & j) = Left(cotK, Len(cotK) - 1)
                            .Range("L" & j) = Left(cotL, Len(cotL) - 1)
                            .Range("O" & j) = Left(cotO, Len(cotO) - 1)
                            If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' nêu xx là VN th́
                                .Range("M" & j) = Left(cotM, Len(cotM) - 1)
                                .Range("N" & j) = Left(cotN, Len(cotN) - 1)
                            End If
                    End If
            Next j
            
            'an hàng rong  khong chua du lieu
            Dim arrBangke As Variant
                arrBangke = .Range("A16:A1585").Value
                For k = 1 To UBound(arrBangke, 1)
                   If arrBangke(k, 1) = "" Then
                        .Rows((k + 15) & ":1585").Hidden = True
                        Exit For
                   End If
                Next k
            ' an cot du thua di
                   .Range("O1:Y1").EntireColumn.Hidden = True
                   

        Dim K10#, P10#, P1603#, P1604#
        Dim H1588#, I1588#
        Dim I1590#, I1591#, I1593#
        Dim I1595#, I1596#, I1597#, I1599#
        Dim I1600#, I1601#, I1602#, I1603#, I1604#
        Dim keyIncoterm As String
        Dim sumVNH As Double, sumVNI As Double, freight#

            ' Lay s?n các giá tri hay dùng
            K10 = .Range("K10").Value
            P10 = .Range("P10").Value
            P1603 = .Range("P1603").Value
            P1604 = .Range("P1604").Value
            keyIncoterm = .Range("O8").Value
        
            ' Tong có xx và ko có xx
            Dim arrBangKeH As Variant, arrBangKeI As Variant
            Dim sumH As Double, sumI As Double
            arrBangKeH = .Range("H16:H" & lastRowT).Value ' ḍng cuoi là dong dm
            arrBangKeI = .Range("I16:I" & lastRowT).Value ' ḍng cuoi là dong dm
            sumH = 0
            sumI = 0
                For k = 1 To UBound(arrBangKeH, 1)
                    If IsNumeric(arrBangKeH(k, 1)) Then
                        If IsNumeric(arrBangKeH(k, 1)) Then sumH = sumH + CDbl(arrBangKeH(k, 1)) ' tông côt H
                        If IsNumeric(arrBangKeI(k, 1)) Then sumI = sumI + CDbl(arrBangKeI(k, 1)) ' tông côt I
                    End If
                Next k
            .Range("H1588").Value = sumH
            .Range("C1586").Value = sumH
            .Range("I1588").Value = sumI
            .Range("C1587").Value = sumI
            .Range("K1606").Value = sumI
            
        
            ' Chi phí nhân công tr?c ti?p
            I1590 = .Range("P1590").Value * K10
            I1591 = .Range("P1591").Value * K10
            I1593 = I1590 + I1591
            .Range("I1590").Value = I1590
            .Range("I1591").Value = I1591
            .Range("I1593").Value = I1593
        
            ' Chi phí phân b?
            I1595 = .Range("P1595").Value * K10
            I1596 = .Range("P1596").Value * K10
            I1597 = .Range("P1597").Value * K10
            I1599 = I1595 + I1596 + I1597
            .Range("I1595").Value = I1595
            .Range("I1596").Value = I1596
            .Range("I1597").Value = I1597
            .Range("I1599").Value = I1599
        
            ' Chi phí xu?t xu?ng (IV)
            I1600 = sumH + sumI + I1593 + I1599
            .Range("I1600").Value = I1600
        
            ' X? lư theo di?u ki?n Incoterm
            Select Case UCase(keyIncoterm)
                Case "EXW", "FCR"
                    I1602 = K10
                    I1603 = (K10 / P10) * P1603
                    I1604 = K10 + I1603
                    I1601 = I1602 - I1600
        
                Case "FOB"
                    I1604 = K10
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
        
                Case Else ' CFR, CIF, DDU, DDP, ...
                    freight = (K10 / P10) * P1604
                    I1604 = K10 - freight
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    K10 = I1604 ' c?p nh?t l?i giá FOB
            End Select
        
            ' Ghi kêt qua
            .Range("I1601").Value = I1601
            .Range("I1602").Value = I1602
            .Range("I1603").Value = I1603
            .Range("I1604").Value = I1604
            .Range("K11").Value = I1604
        
            ' Ghi thông tin CTSH
            .Range("J1606").Value = Round(I1604, 2) & "   - "
            .Range("J1609").Value = Round(I1604, 2)
            
    
    ' CTSH %
    .Range("M1607").Value = Round((I1604 - .Range("K1606").Value) / I1604 * 100, 2) & " %"
          
        'copy CTSH tu wb goc sang wb moi khoi tao
        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            Range("A1:AA1626").Copy
            Range("A1:AA1626").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = so & .Range("P7") ' dat ten sheet vua moi past
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh
         so = so + 1
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
    Next i ' kêt thúc vong lap i ////////////////////
    
    newWb.Activate ' quay tro ve wb moi khoi tao
    Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
    'wb.Close ' tat file excel

 
End With
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub

Sub runUpgradeEUR1()
Dim lastRowW As Integer, lastRowT As Integer, lastRowXK As Double, lastRowDM As Long, lastRowSave As Double
Dim wsXK As Worksheet, wsDM As Worksheet, wsSave As Worksheet
Dim dictXK As Object, dictXKcot17 As Object, dictDM As Object, dictDMcot2 As Object, dictSave As Object, dictSave2 As Object
Dim arrXK As Variant, arrDM As Variant, arrSave As Variant
Dim i As Double
Dim colCountXK As Integer, colCountDM As Integer, colCountSave As Integer
Call unProtected

With ThisWorkbook.Sheets("EUR1")
lastRowW = .Cells(.Rows.Count, "W").End(xlUp).row

    ' dat ten sheet
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsSave = ThisWorkbook.Sheets("Save")
    
    ' khoi tao dict
    Set dictXK = CreateObject("Scripting.Dictionary")
    Set dictXKcot17 = CreateObject("Scripting.Dictionary")
    Set dictDM = CreateObject("Scripting.Dictionary")
    Set dictDMcot2 = CreateObject("Scripting.Dictionary")
    Set dictSave = CreateObject("Scripting.Dictionary")
    Set dictSave2 = CreateObject("Scripting.Dictionary")
    
    
    
    'ḍng cuôi
    lastRowXK = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "B").End(xlUp).row
    lastRowSave = wsSave.Cells(wsSave.Rows.Count, "W").End(xlUp).row
    
    ' khoi tao mang
    arrXK = wsXK.Range("A11:BB" & lastRowXK)
    arrDM = wsDM.Range("A7:Y" & lastRowDM)
    arrSave = wsSave.Range("A2:W" & lastRowSave)
    
    ' sô côt trong mang
    colCountXK = UBound(arrXK, 2)
    colCountDM = UBound(arrDM, 2)
    colCountSave = UBound(arrSave, 2)
    
'cài dat thoi han su dung
    Dim hanchot As Date
        hanchot = DateSerial(2026, 12, 31)
            If Now() > hanchot Then
                MsgBox "Qua han su dung " & CStr(hanchot)
                ThisWorkbook.Close SaveChanges:=False
            End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path
    sFileName = "EUR1" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        
'I. dien du lieu header
    ' 1.1 gán data vào dictXK
    Dim arrRow As Variant ' tao mang tam dê chua ḍng
    Dim j As Double
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRow(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRow(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXK(arrXK(i, 2)) = arrRow ' ' Dùng côt 2 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
           
    '1.2 ghi data tu dictXK vào bang ke EUR1
    Dim key As Variant
    key = Range("Q9").Value
    If dictXK.Exists(key) Then
        .Range("P6") = dictXK(key)(11) ' ty gia
        .Range("O8") = dictXK(key)(18) ' incoterm
    End If

    '1.3 t́m côt P10
    Dim total As Double
    total = 0
    For i = 1 To UBound(arrXK, 1)
        If arrXK(i, 2) = key Then
            If IsNumeric(arrXK(i, 31)) Then ' trap lôi
                total = total + arrXK(i, 31) ' tong tg nguyên tê
            End If
        End If
    Next i
    .Range("P10") = total
 
 ' II dien phân body bên trong bang kê
 ' khoi tao dict moi côt 17 là key xxxxxxxxxxxxxxxxx
 Dim arrRowcot17 As Variant ' tao mang tam dê chua ḍng
 Dim key2 As Variant
    For i = 1 To UBound(arrXK, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
        ReDim arrRowcot17(1 To colCountXK) ' câp lai mang 1 chieu kích thuoc là sô côt
        For j = 1 To colCountXK
            arrRowcot17(j) = arrXK(i, j) 'Lây giá tri  ḍng i, côt j cua arrXK, gán vào vi trí j trong mang arrRow."
        Next j
        dictXKcot17(CStr(arrXK(i, 17))) = arrRowcot17 ' ' Dùng côt 16 làm Key, và gán toàn bô ḍng & côt vào Value
    Next i
    
' tim so luong dong ma dinh muc sp
  ' khoi tao dictDM yyyyyyyyyyyyyyyyy
        Dim counifDM As Integer
        Dim keyDM As Variant
        For i = 1 To UBound(arrDM, 1)
            dictDM(CStr(arrDM(i, 1))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
    
  ' khoi tao dictDMcot2 moi de vlookup zzzzzzzzzzzzzzzzzzzzzzzzz
      Dim keyDM2 As Variant
      Dim stt As Integer
        For i = 1 To UBound(arrDM, 1)
            dictDMcot2(CStr(arrDM(i, 2))) = Array(arrDM(i, 1), arrDM(i, 2), arrDM(i, 6), arrDM(i, 9))
        Next i
        
   ' khoi tao dictSave moi de vlookup wwwwwwwwwwwwwwwwwwwwww
        Dim keySave As Variant
        Dim arrsaveW As Variant
            For i = 1 To UBound(arrSave, 1) ' Duyet tu ḍng 11 den ḍng cuoi cua mang
              ReDim arrsaveW(1 To colCountSave) ' câp lai mang 1 chieu kích thuoc là sô côt w= 23
                For j = 1 To colCountSave
                  arrsaveW(j) = arrSave(i, j) 'Lây giá tri  ḍng i, côt j cua arrSave, gán vào vi trí j trong mang arrRow."
                Next j
                dictSave(CStr(arrSave(i, 23))) = arrsaveW ' Dùng côt 23 làm Key, và gán toàn bô ḍng & côt vào Value
            Next i
            
     'khoi tao dict de tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@
        Dim dictTong As Object, dictDem As Object
        Dim k As Long
        Dim keyTBC As String
        Dim donGia As Double
        Dim donGiaTBC As Double
        Set dictTong = CreateObject("Scripting.Dictionary")
        Set dictDem = CreateObject("Scripting.Dictionary")
        
            For k = 1 To UBound(arrSave, 1) ' duyet mang
                keyTBC = arrSave(k, 23) ' lây giá tri ḍng i côt 23 gán vào keyTBC
                If IsNumeric(arrSave(k, 9)) Then
                    donGia = arrSave(k, 9) 'lây don giá ḍng i côt 9 gán vào don giá
                    If dictTong.Exists(keyTBC) Then ' néu key tôn tai trong dict
                        dictTong(keyTBC) = dictTong(keyTBC) + donGia
                        dictDem(keyTBC) = dictDem(keyTBC) + 1
                    Else ' nguoc lai, nêu key ko tôn tai
                        dictTong.Add keyTBC, donGia ' lay don giá
                        dictDem.Add keyTBC, 1 ' sô lân xuât hien don giá = 1
                    End If
                 End If
            Next k
       
       ' khoi tao dictSave2 moi de vlookup #########################
       Dim arrSave2 As Variant
       Dim keySave2 As String
       Dim boxkeyValue As Collection 'trong Dictionary chi chua 1 giá tri duy nhât (không duoc trùng key), nên muôn luu nhiêu ḍng cho cùng 1 key, phai gom nhiêu ḍng vào 1 Collection
       For i = 1 To UBound(arrSave, 1) ' duyêt mang tu save de luu giá tri vào dictsave2
       keySave2 = CStr(arrSave(i, 23))
            arrSave2 = Array(arrSave(i, 1), arrSave(i, 2), arrSave(i, 4), arrSave(i, 14), arrSave(i, 15)) 'ghi côt 1,2,4,14,15
            If Not dictSave2.Exists(keySave2) Then ' nêu key ko tôn tai trong dict
                Set boxkeyValue = New Collection ' tao bo suu tâp chua data cua các key trùng nhau
                boxkeyValue.Add arrSave2 ' boxkey giông nhu là 1 mang trung gian
                dictSave2.Add keySave2, boxkeyValue ' ghi data t? boxkeyvalue vào dictsave2
            Else
                dictSave2(keySave2).Add arrSave2 ' nêu ko trung th́ ko cân boxkey, ghi truc tiep mang arrsave2 và dictsave2
            End If
       Next i
       

' bat dau vong lap chinh dien phan body/////////////////
        Dim so As Integer
        so = 1
    For i = 16 To lastRowW ' ****** cot moc vong lap de xuat file excel
        ThisWorkbook.Sheets("EUR1").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & i) ' mă SP vao ô P7 xxxxxxxxxxxxxxxxxxxxxxxxxx
        '.Range("Q10") = .Range("W" & i) ' mă SP vao ô P7
        key2 = CStr(.Range("V" & i))
        If dictXKcot17.Exists(key2) Then
            .Range("K7") = dictXKcot17(key2)(23) 'tên sp
            .Range("K8") = Left(dictXKcot17(key2)(22), 6) 'HS code
            .Range("P8") = dictXKcot17(key2)(25) 'don giá
            .Range("L9") = dictXKcot17(key2)(28) 'dvt
            .Range("K9") = dictXKcot17(key2)(27) 'sl
            .Range("P9") = dictXKcot17(key2)(27) 'sl
            .Range("B10") = ChrW(272) & ChrW(417) & "n giá " & .Range("O8") & ": " & dictXKcot17(key2)(25) 'don giá incoterm
            .Range("L10") = "USD"
            .Range("L11") = "USD"
            .Range("I10") = "Tr" & ChrW(7883) & " giá " & .Range("O8") ' tri gia incoterm
            .Range("K10") = .Range("P8") * .Range("P9") ' tri gia tkx
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
        End If
        
  'tính countif  t́m sl ḍng dm yyyyyyyyyyyyyyyyyy
        keyDM = CStr(.Range("P7"))
        counifDM = 0
        For j = 1 To UBound(arrDM, 1)
            If arrDM(j, 1) = keyDM Then
                counifDM = counifDM + 1
            End If
        Next j
        .Range("P5") = counifDM ' gán sl vào dong cuoi o cot T
        .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
    
 'chay vong lap dien gia tri trong table zzzzzzzzzzzzzzzzzzz
        stt = 0
        lastRowT = .Cells(.Rows.Count, "T").End(xlUp).row
            For j = 16 To lastRowT
                 stt = stt + 1
                .Range("A" & j) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
                ' dien cot E(dm) và cot P mă NVL
                keyDM2 = CStr(stt & .Range("P7"))
                If dictDMcot2.Exists(keyDM2) Then
                    .Range("E" & j) = dictDMcot2(keyDM2)(3) ' dm
                    .Range("P" & j) = dictDMcot2(keyDM2)(2) 'mă nvl
                    .Range("F" & j) = .Range("E" & j) * .Range("P9") ' tinh sl
                    .Range("Q" & j) = "'" & .Range("Q9") & .Range("P" & j) ' tao cot phu
                End If
                
                ' dien các côt B,C,D,J,R,S wwwwwwwwwwwwwwwwwwwwwwww
                keySave = .Range("Q" & j)
                If dictSave.Exists(keySave) Then
                    .Range("B" & j) = dictSave(keySave)(7) ' tên nvl
                    .Range("C" & j) = Left(dictSave(keySave)(6), 6) ' HS code
                    .Range("D" & j) = dictSave(keySave)(12) ' dvt
                    .Range("J" & j) = dictSave(keySave)(8) ' xuât xu
                    .Range("R" & j) = dictSave(keySave)(16) ' ty giá
                    .Range("S" & j) = dictSave(keySave)(3) ' loai h́nh
                End If
                
                
                'tính don gia trung binh @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
                If dictTong.Exists(keySave) Then
                    donGiaTBC = dictTong(keySave) / dictDem(keySave)
                    .Range("G" & j) = donGiaTBC ' tính trung b́nh công côt G
                End If
                
                '  tinh tri giá có XX & ko có XX
                If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' ma lh de trong => mua trong nuoc
                    .Range("H" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia trong nuoc côt H
                Else
                    .Range("I" & j) = .Range("F" & j) * .Range("G" & j) 'tinh tri gia ngoai nuoc côt I
                End If
                
                
                ' dien các côt K,L,M,N,O ####################
          
                Dim item ' =  Dim item As Variant
                Dim cotK As String, cotL As String, cotM As String, cotN As String, cotO As String
                    keySave2 = CStr(.Range("Q" & j))
                    cotK = ""
                    cotL = ""
                    cotM = ""
                    cotN = ""
                    cotO = ""
                    If dictSave2.Exists(keySave2) Then
                        For Each item In dictSave2(keySave2) ' cho biên item lap trong collection = dictsave2
                            cotK = cotK & item(0) & ";" 'lay côt 1 là sô tkn
                            cotL = cotL & item(1) & ";" 'lay côt 1 là ngày tkn
                            cotO = cotO & item(2) & ";" 'lay côt 1 là sô ḍng hàng
                            cotM = cotM & item(3) & ";" 'lay côt 1 là sô form X,PL X, CO
                            cotN = cotN & item(4) & ";" 'lay côt 1 là ngày form X,PL X, CO
                            
                        Next ' xoá dâu ; o cuoi di
                            .Range("K" & j) = Left(cotK, Len(cotK) - 1)
                            .Range("L" & j) = Left(cotL, Len(cotL) - 1)
                            .Range("O" & j) = Left(cotO, Len(cotO) - 1)
                            If .Range("J" & j) = "Vi" & ChrW(7879) & "t Nam" Then ' nêu xx là VN th́
                                .Range("M" & j) = Left(cotM, Len(cotM) - 1)
                                .Range("N" & j) = Left(cotN, Len(cotN) - 1)
                            End If
                    End If
            Next j
            
            'an hàng rong  khong chua du lieu
            Dim arrBangke As Variant
                arrBangke = .Range("A16:A1585").Value
                For k = 1 To UBound(arrBangke, 1)
                   If arrBangke(k, 1) = "" Then
                        .Rows((k + 15) & ":1585").Hidden = True
                        Exit For
                   End If
                Next k
            ' an cot du thua di
                   .Range("O1:Y1").EntireColumn.Hidden = True
                   

        Dim K10#, P10#, P1603#, P1604#
        Dim H1588#, I1588#
        Dim I1590#, I1591#, I1593#
        Dim I1595#, I1596#, I1597#, I1599#
        Dim I1600#, I1601#, I1602#, I1603#, I1604#
        Dim keyIncoterm As String
        Dim sumVNH As Double, sumVNI As Double, freight#

            ' Lay s?n các giá tri hay dùng
            K10 = .Range("K10").Value
            P10 = .Range("P10").Value
            P1603 = .Range("P1603").Value
            P1604 = .Range("P1604").Value
            keyIncoterm = .Range("O8").Value
        
            ' Tong có xx và ko có xx
            Dim arrBangKeH As Variant, arrBangKeI As Variant
            Dim sumH As Double, sumI As Double
            arrBangKeH = .Range("H16:H" & lastRowT).Value ' ḍng cuoi là dong dm
            arrBangKeI = .Range("I16:I" & lastRowT).Value ' ḍng cuoi là dong dm
            sumH = 0
            sumI = 0
                For k = 1 To UBound(arrBangKeH, 1)
                    If IsNumeric(arrBangKeH(k, 1)) Then
                        If IsNumeric(arrBangKeH(k, 1)) Then sumH = sumH + CDbl(arrBangKeH(k, 1)) ' tông côt H
                        If IsNumeric(arrBangKeI(k, 1)) Then sumI = sumI + CDbl(arrBangKeI(k, 1)) ' tông côt I
                    End If
                Next k
            .Range("H1588").Value = sumH
            .Range("C1586").Value = sumH
            .Range("I1588").Value = sumI
            .Range("C1587").Value = sumI
            .Range("K1606").Value = sumI
            
        
            ' Chi phí nhân công tr?c ti?p
            I1590 = .Range("P1590").Value * K10
            I1591 = .Range("P1591").Value * K10
            I1593 = I1590 + I1591
            .Range("I1590").Value = I1590
            .Range("I1591").Value = I1591
            .Range("I1593").Value = I1593
        
            ' Chi phí phân b?
            I1595 = .Range("P1595").Value * K10
            I1596 = .Range("P1596").Value * K10
            I1597 = .Range("P1597").Value * K10
            I1599 = I1595 + I1596 + I1597
            .Range("I1595").Value = I1595
            .Range("I1596").Value = I1596
            .Range("I1597").Value = I1597
            .Range("I1599").Value = I1599
        
            ' Chi phí xuât xuong (IV)
            I1600 = sumH + sumI + I1593 + I1599
            .Range("I1600").Value = I1600
        
            ' X? lư theo di?u ki?n Incoterm
            Select Case UCase(keyIncoterm)
                Case "EXW", "FCR"
                    .Range("K11") = K10 + (K10 / P10) * P1603 ' tri gia FOB
                    .Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
                    I1602 = K10
                    I1603 = (K10 / P10) * P1603
                    I1604 = K10 + I1603
                    I1601 = I1602 - I1600
                    
                    ' Tính EUR1
                    .Range("C1611") = P1603 ' tong VII phi van chuyen = Tông các chi phí tu công ty den cang xuât (1):
                    
                    'tính tông TG EXW:
                    Dim tongEXW As Double
                     key = Range("Q9").Value
                     tongEXW = 0
                     For k = 1 To UBound(arrXK, 1)
                        If arrXK(k, 2) = key Then
                            If IsNumeric(arrXK(k, 31)) Then
                                tongEXW = tongEXW + arrXK(k, 31)
                            End If
                        End If
                    Next k
                    .Range("C1612") = tongEXW ' tong tg EXW
                    '.Range("C1612") = Application.SumIf(wsXK.Range("B11:B" & lastRow4), .Range("Q9"), wsXK.Range("AE11:AE" & lastRow4)) 'tông tri giá exw
                    
                    .Range("C1613") = (.Range("C1611") + .Range("C1612")) / .Range("C1612") ' he sô K
                    .Range("C1614") = .Range("P8") / .Range("C1613")
                    .Range("C1615") = (H1588 + I1588) / I1602
        
                Case "FOB"
                    .Range("K11") = K10 ' tri gia FOB
                    .Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
                    I1604 = K10
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    
                    ' Tính EUR1
                    .Range("C1611") = P1603 ' tong VII phi van chuyen = Tông các chi phí tu công ty den cang xuât (1):
                    
                    ' tong tg FOB
                    Dim tongFOB As Double
                     key = Range("Q9").Value
                     tongFOB = 0
                     For k = 1 To UBound(arrXK, 1)
                        If arrXK(k, 2) = key Then
                            If IsNumeric(arrXK(k, 31)) Then
                                tongFOB = tongFOB + arrXK(k, 31)
                            End If
                        End If
                    Next k
                    .Range("C1612") = tongFOB - P1603 ' tong tg EXW
                    '.Range("C1612") = Application.SumIf(wsXK.Range("B11:B" & lastRow4), .Range("Q9"), wsXK.Range("AE11:AE" & lastRow4)) - .Range("C1611") 'tông tri giá EXW
                    
                    .Range("C1613") = (.Range("C1611") + .Range("C1612")) / .Range("C1612") ' he sô K
                    .Range("C1614") = .Range("P8") / .Range("C1613")
                    .Range("C1615") = (H1588 + I1588) / I1602
        
                Case Else ' CFR, CIF, DDU, DDP, ...
                    freight = (K10 / P10) * P1604
                    I1604 = K10 - freight
                    I1603 = (K10 / P10) * P1603
                    I1602 = I1604 - I1603
                    I1601 = I1602 - I1600
                    K10 = I1604 ' câp nhât lai giá FOB
                    .Range("K11") = I1604 ' tri gia FOB
                    .Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & I1604 / .Range("K9") & " USD" ' don gia FOB
                    
                    ' Tính EUR1
                    .Range("C1611") = P1603 ' tong VII phi van chuyen = Tông các chi phí tu công ty den cang xuât (1):
                    ' tong tg CFR, CIF, DDU, DDP, ...
                    Dim tongCD As Double
                     key = Range("Q9").Value
                     tongCD = 0
                     For k = 1 To UBound(arrXK, 1)
                        If arrXK(k, 2) = key Then
                            If IsNumeric(arrXK(k, 31)) Then
                                tongCD = tongCD + arrXK(k, 31)
                            End If
                        End If
                    Next k
                    .Range("C1612") = tongCD - P1604 - P1603 ' tong tg EXW = CIF - OF - trucking fee
                    '.Range("C1612") = Application.SumIf(wsXK.Range("B11:B" & lastRow4), .Range("Q9"), wsXK.Range("AE11:AE" & lastRow4)) 'tông tri giá exw
                    
                    .Range("C1613") = (.Range("C1611") + .Range("C1612")) / .Range("C1612") ' he sô K
                    .Range("C1614") = .Range("P8") / .Range("C1613")
                    .Range("C1615") = (H1588 + I1588) / I1602
            End Select
        
            ' Ghi kêt qua
            .Range("I1601").Value = I1601
            .Range("I1602").Value = I1602
            .Range("I1603").Value = I1603
            .Range("I1604").Value = I1604
            .Range("K11").Value = I1604
        
            ' Ghi thông tin EUR1
            .Range("J1606").Value = Round(I1604, 2) & "   - "
            .Range("J1609").Value = Round(I1604, 2)
            
    
    ' EUR1 %
    .Range("M1607").Value = Round((I1604 - .Range("K1606").Value) / I1604 * 100, 2) & " %"
          
        'copy EUR1 tu wb goc sang wb moi khoi tao
        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            Range("A1:AA1623").Copy
            Range("A1:AA1623").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = so & .Range("P7") ' dat ten sheet vua moi past
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh
         so = so + 1
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
    Next i ' kêt thúc vong lap i ////////////////////
    
    newWb.Activate ' quay tro ve wb moi khoi tao
    Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
    'wb.Close ' tat file excel

 
End With
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub


Function CreateNewWb(sWbName As String) As Workbook
 Dim oldWb As Workbook
 Set oldWb = ActiveWorkbook ' tra ve man hinh workbook cu
 Set CreateNewWb = Workbooks.Add ' tao moi workbook
 'CreateNewWb.SaveAs sWbName ' luu ten file theo filename
 oldWb.Activate
 End Function
 
 Function GetWb(sWbName As String, wb As Workbook) As Boolean ' kieu true or false
' neu GetWb = true thi WB tro vao workbook co ten o tham so sWbName
' neu GetWb = false thi chua co file co ten
    Dim i As Long ' kiem tra xem nhung wb dang open
    sWbName = UCase(sWbName)
        For i = 1 To Workbooks.Count
            If UCase(Workbooks(i).Name) = sWbName Then
                GetWb = True
                Set wb = Workbooks(i)
                Exit Function
            End If
         Next i
End Function
