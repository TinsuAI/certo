Option Explicit
Sub congDon()
Dim i As Long
Dim lastRow As Long, lastRow2 As Long, lastRow3 As Long
Dim answer As Integer
lastRow = ThisWorkbook.Sheets("NK2").Cells(Rows.Count, "A").End(xlUp).row
lastRow2 = ThisWorkbook.Sheets("X-N").Cells(Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("NK2").Cells(Rows.Count, "T").End(xlUp).row

Application.ScreenUpdating = False ' ko canh bao
Application.DisplayAlerts = False ' ngung update man hinh
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo CleanUp
answer = MsgBox("Do you want to proceed that ?", vbYesNo) ' hien thi yes/no
    Select Case answer
    
        Case vbYes
        With ThisWorkbook.Sheets("NK2")
            For i = 5 To lastRow
                .Range("Q" & i) = .Range("Q" & i) + .Range("V" & i)
            Next
         ThisWorkbook.Sheets("X-N").Range("A4:V" & lastRow2 + 3).ClearContents
         .Range("V5:V" & lastRow).ClearContents
         .Range("T" & lastRow3 + 1).Value = .Range("V3").Value
         End With
        Case vbNo
            MsgBox ("OK!")
   
    End Select
    
    
    Call deleteDM

CleanUp:     ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

    


End Sub

Sub CongDonArr()
    Dim lastRow As Long, lastRow2 As Long, lastRow3 As Long
    Dim answer As VbMsgBoxResult
    Dim wsNK2 As Worksheet, wsXN As Worksheet
    Dim arrQ As Variant, arrV As Variant
    Dim i As Long
    
    ' Gán worksheet
    Set wsNK2 = ThisWorkbook.Sheets("NK2")
    Set wsXN = ThisWorkbook.Sheets("X-N")
    Application.ScreenUpdating = False ' ko canh bao
    Application.DisplayAlerts = False ' ngung update man hinh
    Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel
    On Error GoTo CleanUp
    
    ' Xác d?nh ḍng cu?i
    lastRow = wsNK2.Range("A5").CurrentRegion.Rows.Count
    lastRow2 = wsXN.Cells(wsXN.Rows.Count, "E").End(xlUp).row
    lastRow3 = wsNK2.Cells(Rows.Count, "T").End(xlUp).row


    ' Hoi nguoi dùng
    answer = MsgBox("Do you want to proceed that?", vbYesNo + vbQuestion, "Confirmation")
    If answer = vbYes Then
        'B1 Gán data cot Q và V vào mang
        arrQ = wsNK2.Range("Q5:Q" & lastRow).Value
        arrV = wsNK2.Range("V5:V" & lastRow).Value
        ' B2 duyet mang
        For i = 1 To UBound(arrQ, 1)
            If IsNumeric(arrQ(i, 1)) = False Then arrQ(i, 1) = 0
            If IsNumeric(arrV(i, 1)) = False Then arrV(i, 1) = 0
            arrQ(i, 1) = arrQ(i, 1) + arrV(i, 1)
        Next i
        'B3 Return ket qua tu mang vào sheet
        wsNK2.Range("Q5:Q" & lastRow).Value = arrQ
    
       wsXN.Range("A4:V" & lastRow2 + 3).ClearContents
         wsNK2.Range("V5:V" & lastRow).ClearContents
         wsNK2.Range("T" & lastRow3 + 1).Value = wsNK2.Range("V3").Value
    Else
        MsgBox "OK!", vbInformation
        
    End If
   Call deleteDM
    
CleanUp:            ' hoan tra ve ban dau
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic

End Sub


Sub XoaLVC()
Dim i, x, lastRow As Integer
Dim lookupRange As Range
With ThisWorkbook.Sheets("LVC")
lastRow = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "Q").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

  .Range("Q9") = ThisWorkbook.Sheets("DM").Range("K6") ' de lay stk vao LVC
  Application.Calculate ' tính lai toàn bo workbook de chay hàm excel
'canh bao loi khi thieu ma tham chieu
    .Range("E1587") = Excel.WorksheetFunction.Count(.Range("E16:E1585")) ' dem gia tri có noi dung
    .Range("Q1587") = Excel.WorksheetFunction.CountA(.Range("Q16:Q1585")) ' dem gia tri co noi dung + ham excel
        If .Range("E1587") <> .Range("Q1587") Then
            UniMsgBoxPos .Range("Q14"), vbCritical, "Thông báo"
        End If
            .Range("E1587") = ""
            .Range("Q1587") = ""
        
    ' tao code de lookup
        For i = 16 To 1585
            If .Range("P" & i) <> "" Then
                .Range("Q" & i) = .Range("Q9") & .Range("P" & i)
            End If
        Next
    
    ' xoa code thua
        For i = 16 To 1585
            If .Range("P" & i) = "" Then
                .Range("W" & i) = ""
            End If
        Next
    
    ' t́m cot ma sp
    x = 49 - Excel.WorksheetFunction.CountBlank(.Range("V16:V65")) ' dem gia tri rong cua 50 dong hang
        For i = 16 To 16 + x
             .Range("W" & i) = Application.WorksheetFunction.VLookup(.Range("V" & i), lookupRange, 5, 0)
        Next
    
    .Range("B9") = ""
    .Range("A16:U1585") = ""
    .Range("P4:P11") = ""
    .Range("K7:K11") = ""
    .Range("L9:L11") = ""
    .Range("I1588:I1604") = ""
    .Range("C1586:C1587") = ""
    .Range("H1588") = ""
    .Range("J1606") = ""
    .Range("J1609") = ""
    .Range("K1606") = ""
    .Range("M1607") = ""
    .Range("L16:N1585").Font.Color = vbBlack ' default mau den cho font chu
    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

End With
End Sub
Sub XoaCTH()
Dim i, x, lastRow As Integer
Dim lookupRange As Range
With ThisWorkbook.Sheets("CTH")
lastRow = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "Q").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

.Range("Q9") = ThisWorkbook.Sheets("DM").Range("K6") ' de lay stk vao CTH
 Application.Calculate ' tính lai toàn bo workbook de chay hàm excel
'canh bao loi khi thieu ma tham chieu
    .Range("E1587") = Excel.WorksheetFunction.Count(.Range("E16:E1585")) ' dem gia tri có noi dung
    .Range("Q1587") = Excel.WorksheetFunction.CountA(.Range("Q16:Q1585")) ' dem gia tri co noi dung + ham excel
        If .Range("E1587") <> .Range("Q1587") Then
            UniMsgBoxPos .Range("Q14"), vbCritical, "Thông báo"
        End If
            .Range("E1587") = ""
            .Range("Q1587") = ""
        
    ' tao code de lookup
        For i = 16 To 1587
            If .Range("P" & i) <> "" Then
                .Range("Q" & i) = .Range("Q9") & .Range("P" & i)
            End If
        Next
    
    ' xoa code thua
        For i = 16 To 1587
            If .Range("P" & i) = "" Then
                .Range("W" & i) = ""
            End If
        Next
    
    ' t́m cot ma sp
    x = 49 - Excel.WorksheetFunction.CountBlank(.Range("V16:V65")) ' dem gia tri rong cua 50 dong hang
        For i = 16 To 16 + x
             .Range("W" & i) = Application.WorksheetFunction.VLookup(.Range("V" & i), lookupRange, 5, 0)
        Next

    .Range("L9:L11") = ""
    .Range("A16:U1585") = ""
    .Range("P5:P10") = ""
    .Range("K7:K11") = ""
    .Range("I1588:I1604") = ""
    .Range("C1586:C1587") = ""
    .Range("H1588") = ""
    .Range("L16:N1585").Font.Color = vbBlack ' default mau den cho font chu
    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
End With
End Sub

Sub XoaCTSH()
Dim i, x, lastRow As Integer
Dim lookupRange As Range
With ThisWorkbook.Sheets("CTSH")
lastRow = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "Q").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

.Range("Q9") = ThisWorkbook.Sheets("DM").Range("K6") ' de lay stk vao CTSH
Application.Calculate ' tính lai toàn bo workbook de chay hàm excel
'canh bao loi khi thieu ma tham chieu
    .Range("E1587") = Excel.WorksheetFunction.Count(.Range("E16:E1585")) ' dem gia tri có noi dung
    .Range("Q1587") = Excel.WorksheetFunction.CountA(.Range("Q16:Q1585")) ' dem gia tri co noi dung + ham excel
        If .Range("E1587") <> .Range("Q1587") Then
            UniMsgBoxPos .Range("Q14"), vbCritical, "Thông báo"
        End If
            .Range("E1587") = ""
            .Range("Q1587") = ""
        
    ' tao code de lookup
        For i = 16 To 1587
            If .Range("P" & i) <> "" Then
                .Range("Q" & i) = .Range("Q9") & .Range("P" & i)
            End If
        Next
    
    ' xoa code thua
        For i = 16 To 1587
            If .Range("P" & i) = "" Then
                .Range("W" & i) = ""
            End If
        Next
    
    ' t́m cot ma sp
    x = 49 - Excel.WorksheetFunction.CountBlank(.Range("V16:V65")) ' dem gia tri rong cua 50 dong hang
        For i = 16 To 16 + x
             .Range("W" & i) = Application.WorksheetFunction.VLookup(.Range("V" & i), lookupRange, 5, 0)
        Next

    .Range("L9:L11") = ""
    .Range("A16:U1585") = ""
    .Range("P5:P10") = ""
    .Range("K7:K11") = ""
    .Range("I1588:I1604") = ""
    .Range("C1586:C1587") = ""
    .Range("H1588") = ""
    .Range("L16:N1585").Font.Color = vbBlack ' default mau den cho font chu
    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
End With
End Sub


Sub XoaRVC()
Dim i, x, lastRow As Integer
Dim lookupRange As Range
With ThisWorkbook.Sheets("RVC")
lastRow = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "Q").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

.Range("Q9") = ThisWorkbook.Sheets("DM").Range("K6") ' de lay stk vao RVC
 Application.Calculate ' tính lai toàn bo workbook de chay hàm excel
'canh bao loi khi thieu ma tham chieu
    .Range("E1587") = Excel.WorksheetFunction.Count(.Range("E16:E1585")) ' dem gia tri có noi dung
    .Range("Q1587") = Excel.WorksheetFunction.CountA(.Range("Q16:Q1585")) ' dem gia tri co noi dung + ham excel
        If .Range("E1587") <> .Range("Q1587") Then
            UniMsgBoxPos .Range("Q14"), vbCritical, "Thông báo"
        End If
            .Range("E1587") = ""
            .Range("Q1587") = ""
        
    ' tao code de lookup
        For i = 16 To 1587
            If .Range("P" & i) <> "" Then
                .Range("Q" & i) = .Range("Q9") & .Range("P" & i)
            End If
        Next
    
    ' xoa code thua
        For i = 16 To 1587
            If .Range("P" & i) = "" Then
                .Range("W" & i) = ""
            End If
        Next
    
    ' t́m cot ma sp
    x = 49 - Excel.WorksheetFunction.CountBlank(.Range("V16:V65")) ' dem gia tri rong cua 50 dong hang
        For i = 16 To 16 + x
             .Range("W" & i) = Application.WorksheetFunction.VLookup(.Range("V" & i), lookupRange, 5, 0)
        Next
    

    .Range("A16:U1585") = ""
    .Range("P5:P10") = ""
    .Range("K7:K11") = ""
    .Range("L9:L11") = ""
    .Range("I1588:I1604") = ""
    .Range("C1586:C1587") = ""
    .Range("H1588") = ""
    .Range("J1606") = ""
    .Range("J1609") = ""
    .Range("K1606") = ""
    .Range("M1607") = ""
    .Range("L16:N1585").Font.Color = vbBlack ' default mau den cho font chu
    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

End With
End Sub


Sub XoaEUR()
Dim i, x, lastRow As Integer
Dim lookupRange As Range
With ThisWorkbook.Sheets("EUR1")
lastRow = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "Q").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

.Range("Q9") = ThisWorkbook.Sheets("DM").Range("K6") ' de lay stk vao RVC
 Application.Calculate ' tính lai toàn bo workbook de chay hàm excel
'canh bao loi khi thieu ma tham chieu
    .Range("E1587") = Excel.WorksheetFunction.Count(.Range("E16:E1585")) ' dem gia tri có noi dung
    .Range("Q1587") = Excel.WorksheetFunction.CountA(.Range("Q16:Q1585")) ' dem gia tri co noi dung + ham excel
        If .Range("E1587") <> .Range("Q1587") Then
            UniMsgBoxPos .Range("Q14"), vbCritical, "Thông báo"
        End If
            .Range("E1587") = ""
            .Range("Q1587") = ""
        
    ' tao code de lookup
        For i = 16 To 1587
            If .Range("P" & i) <> "" Then
                .Range("Q" & i) = .Range("Q9") & .Range("P" & i)
            End If
        Next
    
    ' xoa code thua
        For i = 16 To 1587
            If .Range("P" & i) = "" Then
                .Range("W" & i) = ""
            End If
        Next
    
    ' t́m cot ma sp
    x = 49 - Excel.WorksheetFunction.CountBlank(.Range("V16:V65")) ' dem gia tri rong cua 50 dong hang
        For i = 16 To 16 + x
             .Range("W" & i) = Application.WorksheetFunction.VLookup(.Range("V" & i), lookupRange, 5, 0)
        Next
    
    .Range("A16:U1585") = ""
    .Range("P5:P10") = ""
    .Range("K7:K11") = ""
    .Range("L9:L11") = ""
    .Range("B10:B11") = ""
    .Range("C1611:C615") = ""
    .Range("I1588:I1604") = ""
    .Range("C1586:C1587") = ""
    .Range("H1588") = ""
    .Range("J1606") = ""
    .Range("J1609") = ""
    .Range("K1606") = ""
    .Range("M1607") = ""
    .Range("L16:N1585").Font.Color = vbBlack ' default mau den cho font chu
    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

End With
End Sub
